"""
PravaasiDesk server — the glue between Bolna, Cartesia, and your dashboard.

Run:  pip install fastapi uvicorn httpx python-dotenv
      uvicorn server:app --reload --port 8000
Expose to Bolna with: ngrok http 8000   (Bolna needs a public URL for tools/webhooks)

Env vars (.env):
  BOLNA_API_KEY=bn-xxxx
  BOLNA_AGENT_ID=<your agent id from platform.bolna.ai>
  CARTESIA_API_KEY=sk_car_xxxx
  CARTESIA_HINDI_VOICE_ID=<Saathi's warm Hindi voice — the SAME voice the caller hears>
  CARTESIA_KANNADA_VOICE_ID=<optional: a localized/dedicated Kannada voice. If unset,
                             we render the card with the Hindi voice id at language=kn,
                             so "Saathi's own voice" speaks Kannada — same narrative,
                             less moving parts. See /api/admin/localize below.>
  CARTESIA_VOICE_ID=<back-compat fallback if the two above are unset>
  ANTHROPIC_API_KEY=sk-ant-xxxx   (optional — best-effort Hindi→Kannada symptom translation)
"""
import os, time, uuid, json, datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import httpx
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CARTESIA_VERSION = os.environ.get("CARTESIA_VERSION", "2025-04-16")
CARTESIA_MODEL = os.environ.get("CARTESIA_MODEL", "sonic-3")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")  # set to ngrok URL for real SMS links

def hindi_voice():
    return os.environ.get("CARTESIA_HINDI_VOICE_ID") or os.environ.get("CARTESIA_VOICE_ID", "")

def kannada_voice():
    # Prefer a dedicated/localized Kannada voice; otherwise use Saathi's Hindi voice at language=kn.
    return os.environ.get("CARTESIA_KANNADA_VOICE_ID") or hindi_voice()

# ---------- in-memory case state (single demo case; swap for Supabase later) ----------
STATE = {"call_active": False, "events": [], "case": {}}

def push(ev: dict):
    ev["ts"] = time.time()
    STATE["events"].append(ev)

# ---------- dashboard polls this ----------
@app.get("/api/state")
def get_state():
    return STATE

@app.post("/api/reset")
def reset():
    STATE.update({"call_active": False, "events": [], "case": {}})
    return {"ok": True}

# =====================================================================
# 1) BOLNA WEBHOOK — set this URL in Agent → Analytics tab → Webhook
#    Bolna posts call lifecycle + extracted data (dispositions) here.
# =====================================================================
@app.post("/webhook/bolna")
async def bolna_webhook(req: Request):
    payload = await req.json()
    status = payload.get("status", "")
    if status in ("ringing", "in-progress", "started"):
        STATE["call_active"] = True
        push({"type": "case_open", "id": f"PD-2026-{uuid.uuid4().hex[:4].upper()}",
              "date": datetime.date.today().strftime("%d %b %Y")})
    if status in ("completed", "ended", "call_ended"):
        STATE["call_active"] = False
        push({"type": "call_end"})
    # Bolna "extracted_data" / dispositions land here post-call — map to case fields
    extracted = payload.get("extracted_data") or payload.get("dispositions") or {}
    field_map = {"name": "name", "home_state": "home", "city": "city",
                 "trade": "trade", "language": "lang"}
    for k, fid in field_map.items():
        if extracted.get(k):
            STATE["case"][k] = extracted[k]
            push({"type": "field", "field": fid, "value": extracted[k]})
    # live transcript chunks (if enabled on your plan). Bolna sends either a string
    # or a list of {role/speaker, text} turns — stream each turn to the dashboard.
    tr = payload.get("transcript")
    if isinstance(tr, list):
        for turn in tr:
            who = "worker" if str(turn.get("role") or turn.get("speaker", "")).lower() in ("user", "human", "caller", "worker") else "agent"
            text = turn.get("text") or turn.get("content") or ""
            if text:
                push({"type": "transcript", "who": who, "text": text[:240]})
    elif isinstance(tr, str) and tr:
        push({"type": "transcript", "who": "system", "text": tr[:240]})
    return {"ok": True}

# =====================================================================
# 2) CUSTOM TOOL: file wage complaint
#    Bolna Agent → Tools tab → Custom API tool pointing to this endpoint.
#    The LLM calls it mid-conversation with extracted parameters.
#    Tool schema to paste in Bolna:
#    { "name": "file_wage_complaint",
#      "description": "File a wage theft complaint on Shram Suvidha when the worker reports unpaid wages. Collect contractor name, amount in rupees, work site, and period first.",
#      "parameters": { "worker_name": "string", "contractor": "string",
#                      "amount": "string", "site": "string", "period": "string" } }
# =====================================================================
@app.post("/api/tools/file-complaint")
async def file_complaint(req: Request):
    p = await req.json()
    ref = f"SS/KA/2026/{uuid.uuid4().hex[:5].upper()}"
    push({"type": "agent", "agent": "haq"})
    push({"type": "field", "field": "issues", "value": f"Wage theft — ₹{p.get('amount','?')}"})
    push({"type": "complaint", "data": {
        "name": p.get("worker_name", STATE["case"].get("name", "Worker")),
        "contractor": p.get("contractor", "—"), "amount": p.get("amount", "—"),
        "site": p.get("site", "—"), "period": p.get("period", "—"), "ref": ref}})
    # Return value is spoken context for the agent — keep it short & actionable
    return {"status": "filed", "reference_number": ref,
            "next_step": "Contractor receives notice within 7 days. Reference sent to worker by SMS."}

# =====================================================================
# CARTESIA helpers
# =====================================================================
async def cartesia_localize(source_voice_id: str, language: str, name: str, description: str = ""):
    """Create a NEW voice id from an existing voice, localized to `language`.
    NOTE: Cartesia Localize supports hi/ta/te (and many others) but NOT kn at the time
    of writing — so this is used for ta/te demos. For the Kannada card we instead pass
    the Hindi voice id directly at language=kn (multilingual TTS), which gives the same
    'Saathi's own voice speaks Kannada' narrative without the unsupported localize step."""
    async with httpx.AsyncClient(timeout=60) as cx:
        r = await cx.post("https://api.cartesia.ai/voices/localize",
            headers={"X-API-Key": os.environ["CARTESIA_API_KEY"],
                     "Cartesia-Version": CARTESIA_VERSION,
                     "Content-Type": "application/json"},
            json={"voice_id": source_voice_id, "name": name,
                  "description": description or f"PravaasiDesk Saathi voice localized to {language}",
                  "language": language, "original_speaker_gender": "male"})
        r.raise_for_status()
        return r.json()

def pcm16_to_wav(pcm: bytes, sample_rate: int = 44100, channels: int = 1) -> bytes:
    """Wrap raw 16-bit PCM in a WAV header so the browser <audio> can play it."""
    import wave, io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)            # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()

async def cartesia_tts_sse(text: str, voice_id: str, language: str):
    """Stream TTS over SSE (raw PCM — the only container SSE supports), aggregating
    audio + word timestamps. Returns (wav_bytes, words) with words=[{w,start,end}].
    Raises on failure so health_clip can fall back to /tts/bytes."""
    import base64
    SR = 44100
    audio = bytearray()
    words = []
    body = {"model_id": CARTESIA_MODEL, "transcript": text,
            "voice": {"mode": "id", "id": voice_id},
            "language": language, "add_timestamps": True,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": SR}}
    async with httpx.AsyncClient(timeout=60) as cx:
        async with cx.stream("POST", "https://api.cartesia.ai/tts/sse",
            headers={"X-API-Key": os.environ["CARTESIA_API_KEY"],
                     "Cartesia-Version": CARTESIA_VERSION,
                     "Content-Type": "application/json"}, json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                if ev.get("type") == "chunk" and ev.get("data"):
                    audio.extend(base64.b64decode(ev["data"]))
                elif ev.get("type") == "timestamps":
                    wt = ev.get("word_timestamps") or {}
                    ws, ss, es = wt.get("words", []), wt.get("start", []), wt.get("end", [])
                    for i, w in enumerate(ws):
                        words.append({"w": w,
                                      "start": ss[i] if i < len(ss) else None,
                                      "end": es[i] if i < len(es) else None})
                elif ev.get("type") == "error":
                    raise RuntimeError(ev.get("message", "cartesia sse error"))
    if not audio:
        raise RuntimeError("cartesia sse returned no audio")
    return pcm16_to_wav(bytes(audio), SR), words

async def cartesia_tts_bytes(text: str, voice_id: str, language: str):
    """Fallback: plain mp3 bytes, no timestamps."""
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post("https://api.cartesia.ai/tts/bytes",
            headers={"X-API-Key": os.environ["CARTESIA_API_KEY"],
                     "Cartesia-Version": CARTESIA_VERSION,
                     "Content-Type": "application/json"},
            json={"model_id": CARTESIA_MODEL, "transcript": text,
                  "voice": {"mode": "id", "id": voice_id}, "language": language,
                  "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}})
        r.raise_for_status()
        return r.content

# Pre-stage helper: run ONCE before the demo to mint a Kannada-capable localized voice
# from Saathi's Hindi voice (for ta/te; kn falls back to direct multilingual TTS).
# curl -X POST localhost:8000/api/admin/localize -d '{"language":"ta"}'
@app.post("/api/admin/localize")
async def admin_localize(req: Request):
    body = await req.json()
    lang = body.get("language", "ta")
    src = body.get("source_voice_id") or hindi_voice()
    if not src:
        return {"error": "No source voice id. Set CARTESIA_HINDI_VOICE_ID first."}
    try:
        v = await cartesia_localize(src, lang, f"Saathi-{lang}")
        vid = v.get("id") or v.get("voice_id")
        return {"status": "localized", "language": lang, "voice_id": vid,
                "note": f"Put this in .env as CARTESIA_KANNADA_VOICE_ID (or per-language) and restart."}
    except Exception as e:
        return {"error": str(e)}

# Best-effort Hindi→Kannada translation (dict stays primary for demo robustness)
SYMPTOM_KANNADA = {  # tiny lookup for demo robustness; LLM fallback below for unseen symptoms
    "pet dard": "ಹೊಟ್ಟೆ ನೋವು ಇದೆ", "stomach pain": "ಹೊಟ್ಟೆ ನೋವು ಇದೆ",
    "bukhar": "ಜ್ವರ ಇದೆ", "fever": "ಜ್ವರ ಇದೆ",
    "chest pain": "ಎದೆ ನೋವು ಇದೆ", "seene mein dard": "ಎದೆ ನೋವು ಇದೆ",
}

async def symptom_to_kannada(symptom_hindi: str) -> str:
    s = (symptom_hindi or "").lower()
    for k, v in SYMPTOM_KANNADA.items():
        if k in s:
            return v
    # LLM fallback — only if a key is configured; otherwise generic phrase
    if os.environ.get("ANTHROPIC_API_KEY") and symptom_hindi:
        try:
            async with httpx.AsyncClient(timeout=15) as cx:
                r = await cx.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": "claude-haiku-4-5", "max_tokens": 80,
                          "messages": [{"role": "user", "content":
                              f"Translate this patient symptom into natural Kannada (Kannada script only, "
                              f"a short clause a hospital nurse would understand, no preamble): {symptom_hindi}"}]})
                r.raise_for_status()
                blocks = r.json().get("content", [])
                txt = next((b.get("text") for b in blocks if b.get("type") == "text"), "")
                if txt.strip():
                    return txt.strip()
        except Exception as e:
            print("Kannada translation fallback failed:", e)
    return "ಆರೋಗ್ಯ ಸಮಸ್ಯೆ ಇದೆ"

# =====================================================================
# 3) CUSTOM TOOL: generate Kannada hospital voice card (CARTESIA)
#    Tool schema:
#    { "name": "create_hospital_voice_card",
#      "description": "When the worker reports a health problem and cannot speak the local language, generate a Kannada audio card describing their symptoms that they can play to hospital staff.",
#      "parameters": { "worker_name": "string", "symptom_hindi": "string" } }
#
#    STANDOUT: rendered in Saathi's OWN voice speaking Kannada (Cartesia multilingual /
#    localized voice) + word-level timestamps drive the karaoke captions on the dashboard.
# =====================================================================
@app.post("/api/tools/health-clip")
async def health_clip(req: Request):
    p = await req.json()
    name = p.get("worker_name", STATE["case"].get("name", "Worker"))
    symptom = await symptom_to_kannada(p.get("symptom_hindi", ""))
    kannada = (f"ನಮಸ್ಕಾರ. ಇವರ ಹೆಸರು {name}. ಇವರಿಗೆ ಎರಡು ದಿನದಿಂದ {symptom}. "
               f"ಇವರಿಗೆ ಕನ್ನಡ ಬರುವುದಿಲ್ಲ. ದಯವಿಟ್ಟು ಸಹಾಯ ಮಾಡಿ. ತುರ್ತು ಸಂಪರ್ಕ: ಪ್ರವಾಸಿ ಡೆಸ್ಕ್.")
    audio_url, words = "", []
    voice = kannada_voice()
    try:
        ext = "wav"
        try:
            content, words = await cartesia_tts_sse(kannada, voice, "kn")  # wav audio + word timestamps
        except Exception as e_sse:
            print("Cartesia SSE failed, falling back to /tts/bytes (no timestamps):", e_sse)
            content = await cartesia_tts_bytes(kannada, voice, "kn")       # mp3, no timestamps
            words = []
            ext = "mp3"
        os.makedirs("static", exist_ok=True)
        fname = f"static/clip_{uuid.uuid4().hex[:6]}.{ext}"
        with open(fname, "wb") as f:
            f.write(content)
        audio_url = f"{PUBLIC_BASE}/{fname}"
    except Exception as e:
        print("Cartesia error (demo continues with text card):", e)
    push({"type": "agent", "agent": "sehat"})
    push({"type": "clip", "data": {"kannada_text": kannada, "audio_url": audio_url, "words": words}})
    return {"status": "created", "spoken_summary":
            "Audio card ready. Tell the worker it has been sent by SMS and they should play it at the hospital counter."}

# =====================================================================
# 4) PROACTIVE FOLLOW-UP — the killer mechanic.
#    POST {"phone": "+91...", "when": "now" | "tomorrow_evening"}
#    "now" rings immediately (on-stage demo). "tomorrow_evening" uses Bolna's native
#    scheduled_at so the call is genuinely booked — "main khud phone karunga" made real.
# =====================================================================
@app.post("/api/followup")
async def followup(req: Request):
    body = await req.json()
    phone = body.get("phone")          # +91XXXXXXXXXX
    when = body.get("when", "now")
    payload = {"agent_id": os.environ["BOLNA_AGENT_ID"],
               "recipient_phone_number": phone,
               # prompt variables → use in agent prompt as {worker_name} etc.
               "user_data": {"worker_name": STATE["case"].get("name", "Ramesh"),
                             "open_issue": STATE["case"].get("issues", "wage complaint"),
                             "call_type": "followup"}}
    when_label = "Now (live)"
    if when == "tomorrow_evening":
        tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))  # IST
        sched = (datetime.datetime.now(tz) + datetime.timedelta(days=1)).replace(
            hour=18, minute=0, second=0, microsecond=0)
        payload["scheduled_at"] = sched.isoformat()
        when_label = sched.strftime("Tomorrow 6:00 PM IST (scheduled via Bolna)")
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post("https://api.bolna.ai/call",
            headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}",
                     "Content-Type": "application/json"}, json=payload)
    push({"type": "followup", "data": {"name": STATE["case"].get("name", "Ramesh"),
                                       "when": when_label}})
    return {"bolna_response": r.json() if r.status_code < 300 else r.text}

app.mount("/static", StaticFiles(directory="static"), name="static") if os.path.isdir("static") else os.makedirs("static", exist_ok=True)
