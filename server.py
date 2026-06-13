"""
PravaasiDesk server — the glue between Bolna, Cartesia, and the dashboard.

Run:
    python3 -m uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import time
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger("pravasidesk")

STATIC_DIR = "static"
AUDIO_DIR = os.path.join(STATIC_DIR, "audio")
STATE_FILE = os.environ.get("STATE_FILE", "demo_state.json")
CARTESIA_VERSION = os.environ.get("CARTESIA_VERSION", "2024-11-13")
CARTESIA_MODEL = os.environ.get("CARTESIA_MODEL_ID") or os.environ.get(
    "CARTESIA_MODEL", "sonic-2"
)

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# TODO: restrict CORS origins in production instead of allowing all origins.


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def today_display() -> str:
    return datetime.date.today().strftime("%d %b %Y")


def current_year() -> int:
    return datetime.date.today().year


def public_base_url() -> str:
    return (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "http://localhost:8000"
    ).rstrip("/")


def public_asset_base_url() -> str:
    return (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or ""
    ).rstrip("/")


def demo_mode_enabled() -> bool:
    return env_flag("DEMO_MODE", True)


def cartesia_configured() -> bool:
    return bool(os.environ.get("CARTESIA_API_KEY") and hindi_voice())


def bolna_configured() -> bool:
    return bool(os.environ.get("BOLNA_API_KEY") and os.environ.get("BOLNA_AGENT_ID"))


def judge_demo_pin_enabled() -> bool:
    return bool(os.environ.get("JUDGE_DEMO_PIN"))


def hindi_voice() -> str:
    return os.environ.get("CARTESIA_HINDI_VOICE_ID") or os.environ.get(
        "CARTESIA_VOICE_ID", ""
    )


def kannada_voice() -> str:
    return os.environ.get("CARTESIA_KANNADA_VOICE_ID") or hindi_voice()


def default_case() -> dict[str, Any]:
    return {
        "id": None,
        "date": None,
        "name": None,
        "home": None,
        "home_state": None,
        "origin": None,
        "city": None,
        "current_city": None,
        "trade": None,
        "work": None,
        "lang": None,
        "language": None,
        "local_language_issue": None,
        "issues": None,
    }


def default_state() -> dict[str, Any]:
    return {
        "call_active": False,
        "call_status": "idle",
        "current_case": default_case(),
        "transcript": [],
        "wage_complaint": None,
        "health_card": None,
        "followup": None,
        "events": [],
        "last_event_at": None,
    }


STATE: dict[str, Any] = default_state()
DEMO_CARD: dict[str, Any] | None = None


def sync_case_aliases(case: dict[str, Any]) -> dict[str, Any]:
    if case.get("home_state") and not case.get("home"):
        case["home"] = case["home_state"]
    if case.get("home") and not case.get("home_state"):
        case["home_state"] = case["home"]
    if case.get("origin") and not case.get("home"):
        case["home"] = case["origin"]
        case["home_state"] = case["origin"]
    if case.get("city") and not case.get("current_city"):
        case["current_city"] = case["city"]
    if case.get("current_city") and not case.get("city"):
        case["city"] = case["current_city"]
    if case.get("trade") and not case.get("work"):
        case["work"] = case["trade"]
    if case.get("work") and not case.get("trade"):
        case["trade"] = case["work"]
    if case.get("language") and not case.get("lang"):
        case["lang"] = case["language"]
    if case.get("lang") and not case.get("language"):
        case["language"] = case["lang"]
    return case


def state_snapshot() -> dict[str, Any]:
    snapshot = copy.deepcopy(STATE)
    snapshot["current_case"] = sync_case_aliases(snapshot["current_case"])
    snapshot["case"] = copy.deepcopy(snapshot["current_case"])
    return snapshot


def load_state() -> None:
    global STATE

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        LOGGER.warning("Failed to load state file %s: %s", STATE_FILE, exc)
        return

    loaded = default_state()
    if isinstance(raw, dict):
        current_case = raw.get("current_case") or raw.get("case") or {}
        if isinstance(current_case, dict):
            loaded["current_case"].update(current_case)
        for key in (
            "call_active",
            "call_status",
            "transcript",
            "wage_complaint",
            "health_card",
            "followup",
            "events",
            "last_event_at",
        ):
            if key in raw:
                loaded[key] = raw[key]

    loaded["current_case"] = sync_case_aliases(loaded["current_case"])
    if not isinstance(loaded.get("events"), list):
        loaded["events"] = []
    if not isinstance(loaded.get("transcript"), list):
        loaded["transcript"] = []
    STATE = loaded


def save_state() -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(state_snapshot(), handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        LOGGER.warning("Failed to save state file %s: %s", STATE_FILE, exc)


def push(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload["ts"] = time.time()
    payload["at"] = payload.get("at") or now_iso()
    STATE["events"].append(payload)
    STATE["last_event_at"] = payload["at"]


def add_transcript(who: str, text: str) -> None:
    if not text:
        return
    turn = {"who": who, "text": text[:1000], "at": now_iso()}
    STATE["transcript"].append(turn)
    push({"type": "transcript", "who": who, "text": turn["text"], "at": turn["at"]})


def set_case_field(
    key: str,
    value: Any,
    *,
    field_id: str | None = None,
    push_event: bool = True,
    dev: bool = False,
) -> None:
    if value in (None, ""):
        return

    case = STATE["current_case"]
    if key in {"home", "home_state", "origin"}:
        case["home"] = value
        case["home_state"] = value
        case["origin"] = value
        field_id = field_id or "home"
    elif key in {"city", "current_city"}:
        case["city"] = value
        case["current_city"] = value
        field_id = field_id or "city"
    elif key in {"trade", "work"}:
        case["trade"] = value
        case["work"] = value
        field_id = field_id or "trade"
    elif key in {"lang", "language"}:
        case["lang"] = value
        case["language"] = value
        field_id = field_id or "lang"
    else:
        case[key] = value
        field_id = field_id or key

    sync_case_aliases(case)
    if push_event:
        push({"type": "field", "field": field_id, "value": value, "dev": dev})


def set_call_status(status: str, active: bool) -> None:
    STATE["call_status"] = status
    STATE["call_active"] = active


def ensure_case_open(case_id: str | None = None) -> None:
    case = STATE["current_case"]
    case_id = case_id or case.get("id") or f"PD-{current_year()}-{uuid.uuid4().hex[:4].upper()}"
    case["id"] = case_id
    case["date"] = case.get("date") or today_display()
    push({"type": "case_open", "id": case["id"], "date": case["date"]})


def reset_state(*, persist: bool = True) -> dict[str, Any]:
    global STATE
    STATE = default_state()
    if persist:
        save_state()
    return state_snapshot()


def parse_amount_estimate(value: Any) -> int | None:
    if value in (None, ""):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def build_reference_id(*, demo: bool) -> str:
    suffix = uuid.uuid4().hex[:5].upper()
    if demo:
        return f"SS/KA/{current_year()}/DEMO-{suffix}"
    return f"SS/KA/{current_year()}/{suffix}"


def update_wage_complaint(
    *,
    worker_name: str,
    employer_name: str,
    amount: str | None,
    site: str,
    period: str,
    city: str | None,
    days_unpaid: int | None,
    status: str,
    reference_id: str,
) -> dict[str, Any]:
    amount_estimate = parse_amount_estimate(amount)
    display_amount = amount or ("—" if amount_estimate is None else str(amount_estimate))
    complaint = {
        "status": status,
        "name": worker_name,
        "worker_name": worker_name,
        "contractor": employer_name,
        "employer_name": employer_name,
        "amount": display_amount,
        "amount_estimate": amount_estimate,
        "site": site,
        "period": period,
        "city": city,
        "days_unpaid": days_unpaid,
        "reference_id": reference_id,
        "ref": reference_id,
        "created_at": now_iso(),
    }
    STATE["wage_complaint"] = complaint
    set_case_field(
        "issues",
        f"Unpaid wages in {city or 'Bengaluru'}" if city else "Unpaid wages",
        field_id="issues",
    )
    push({"type": "agent", "agent": "haq"})
    push({"type": "complaint", "data": complaint})
    return complaint


def persist_audio_file(content: bytes, extension: str) -> str:
    file_name = f"clip_{uuid.uuid4().hex[:6]}.{extension}"
    path = os.path.join(AUDIO_DIR, file_name)
    with open(path, "wb") as handle:
        handle.write(content)
    asset_path = f"/static/audio/{file_name}"
    base_url = public_asset_base_url()
    return f"{base_url}{asset_path}" if base_url else asset_path


# =====================================================================
# Cartesia helpers
# =====================================================================
async def cartesia_localize(
    source_voice_id: str, language: str, name: str, description: str = ""
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.cartesia.ai/voices/localize",
            headers={
                "X-API-Key": os.environ["CARTESIA_API_KEY"],
                "Cartesia-Version": CARTESIA_VERSION,
                "Content-Type": "application/json",
            },
            json={
                "voice_id": source_voice_id,
                "name": name,
                "description": description
                or f"PravaasiDesk Saathi voice localized to {language}",
                "language": language,
                "original_speaker_gender": "male",
            },
        )
        response.raise_for_status()
        return response.json()


def pcm16_to_wav(pcm: bytes, sample_rate: int = 44100, channels: int = 1) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_handle:
        wav_handle.setnchannels(channels)
        wav_handle.setsampwidth(2)
        wav_handle.setframerate(sample_rate)
        wav_handle.writeframes(pcm)
    return buffer.getvalue()


async def cartesia_tts_sse(
    text: str, voice_id: str, language: str
) -> tuple[bytes, list[dict[str, Any]]]:
    import base64

    sample_rate = 44100
    audio = bytearray()
    words: list[dict[str, Any]] = []
    body = {
        "model_id": CARTESIA_MODEL,
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "language": language,
        "add_timestamps": True,
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": sample_rate,
        },
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            "https://api.cartesia.ai/tts/sse",
            headers={
                "X-API-Key": os.environ["CARTESIA_API_KEY"],
                "Cartesia-Version": CARTESIA_VERSION,
                "Content-Type": "application/json",
            },
            json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except Exception:
                    continue
                if event.get("type") == "chunk" and event.get("data"):
                    audio.extend(base64.b64decode(event["data"]))
                elif event.get("type") == "timestamps":
                    word_timestamps = event.get("word_timestamps") or {}
                    word_list = word_timestamps.get("words", [])
                    starts = word_timestamps.get("start", [])
                    ends = word_timestamps.get("end", [])
                    for index, word in enumerate(word_list):
                        words.append(
                            {
                                "w": word,
                                "start": starts[index] if index < len(starts) else None,
                                "end": ends[index] if index < len(ends) else None,
                            }
                        )
                elif event.get("type") == "error":
                    raise RuntimeError(event.get("message", "cartesia sse error"))
    if not audio:
        raise RuntimeError("cartesia sse returned no audio")
    return pcm16_to_wav(bytes(audio), sample_rate), words


async def cartesia_tts_bytes(text: str, voice_id: str, language: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={
                "X-API-Key": os.environ["CARTESIA_API_KEY"],
                "Cartesia-Version": CARTESIA_VERSION,
                "Content-Type": "application/json",
            },
            json={
                "model_id": CARTESIA_MODEL,
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "language": language,
                "output_format": {
                    "container": "mp3",
                    "sample_rate": 44100,
                    "bit_rate": 128000,
                },
            },
        )
        response.raise_for_status()
        return response.content


SYMPTOM_KANNADA = {
    "pet dard": "ಹೊಟ್ಟೆ ನೋವು ಇದೆ",
    "stomach pain": "ಹೊಟ್ಟೆ ನೋವು ಇದೆ",
    "bukhar": "ಜ್ವರ ಇದೆ",
    "fever": "ಜ್ವರ ಇದೆ",
    "chest pain": "ಎದೆ ನೋವು ಇದೆ",
    "seene mein dard": "ಎದೆ ನೋವು ಇದೆ",
}


async def symptom_to_kannada(symptom_hindi: str) -> str:
    symptom = (symptom_hindi or "").lower()
    for key, value in SYMPTOM_KANNADA.items():
        if key in symptom:
            return value
    if os.environ.get("ANTHROPIC_API_KEY") and symptom_hindi:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 80,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Translate this patient symptom into natural Kannada "
                                    "(Kannada script only, short and usable at a hospital desk): "
                                    f"{symptom_hindi}"
                                ),
                            }
                        ],
                    },
                )
                response.raise_for_status()
                blocks = response.json().get("content", [])
                text = next(
                    (block.get("text") for block in blocks if block.get("type") == "text"),
                    "",
                )
                if text.strip():
                    return text.strip()
        except Exception as exc:
            LOGGER.warning("Kannada translation fallback failed: %s", exc)
    return "ಆರೋಗ್ಯ ಸಮಸ್ಯೆ ಇದೆ"


async def generate_health_card(
    *,
    worker_name: str,
    symptom_hindi: str,
    language_from: str,
    language_to: str,
    text: str | None = None,
    gloss: str | None = None,
) -> dict[str, Any]:
    if not text:
        symptom = await symptom_to_kannada(symptom_hindi)
        text = (
            f"ನಮಸ್ಕಾರ. ಇವರ ಹೆಸರು {worker_name}. ಇವರಿಗೆ {symptom}. "
            "ಇವರಿಗೆ ಕನ್ನಡ ಬರುವುದಿಲ್ಲ. ದಯವಿಟ್ಟು ಸಹಾಯ ಮಾಡಿ."
        )

    card = {
        "worker_name": worker_name,
        "language_from": language_from,
        "language_to": language_to,
        "symptom_hindi": symptom_hindi,
        "kannada_text": text,
        "text": text,
        "gloss": gloss,
        "audio_url": None,
        "audio_status": "demo_text_only",
        "error": None,
        "words": [],
        "created_at": now_iso(),
    }

    if not cartesia_configured():
        card["error"] = "Cartesia not configured"
        return card

    voice_id = kannada_voice()
    if not voice_id:
        card["error"] = "Cartesia voice id missing"
        return card

    try:
        try:
            content, words = await cartesia_tts_sse(text, voice_id, "kn")
            card["audio_url"] = persist_audio_file(content, "wav")
            card["audio_status"] = "ready"
            card["words"] = words
        except Exception as sse_exc:
            LOGGER.warning("Cartesia SSE failed, falling back to bytes: %s", sse_exc)
            content = await cartesia_tts_bytes(text, voice_id, "kn")
            card["audio_url"] = persist_audio_file(content, "mp3")
            card["audio_status"] = "ready"
            card["error"] = "Used bytes fallback without timestamps"
    except Exception as exc:
        card["audio_url"] = None
        card["audio_status"] = "demo_text_only"
        card["error"] = str(exc)[:180]
        LOGGER.warning("Cartesia error; continuing with text-only demo card: %s", exc)

    return card


async def generate_card(name: str, symptom_hindi: str) -> dict[str, Any]:
    return await generate_health_card(
        worker_name=name,
        symptom_hindi=symptom_hindi,
        language_from="Hindi",
        language_to="Kannada",
    )


# =====================================================================
# Routes
# =====================================================================
@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse("dashboard.html")


@app.get("/demo")
def demo_dashboard() -> FileResponse:
    return FileResponse("dashboard.html")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "PravaasiDesk",
        "demo_mode": demo_mode_enabled(),
        "cartesia_configured": cartesia_configured(),
        "bolna_configured": bolna_configured(),
        "last_event_at": STATE.get("last_event_at"),
    }


@app.get("/api/config/public")
def public_config() -> dict[str, Any]:
    return {
        "public_base_url": os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "http://localhost:8000",
        "bolna_phone_number": os.environ.get("BOLNA_PHONE_NUMBER"),
        "demo_mode": demo_mode_enabled(),
        "judge_demo_pin_enabled": judge_demo_pin_enabled(),
    }


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return state_snapshot()


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    return reset_state(persist=True)


# =====================================================================
# BOLNA WEBHOOK
# =====================================================================
@app.post("/webhook/bolna")
async def bolna_webhook(req: Request) -> dict[str, Any]:
    payload = await req.json()
    status = str(payload.get("status", "")).lower()

    if status in {"ringing", "in-progress", "started"}:
        set_call_status(status, True)
        if not STATE["current_case"].get("id"):
            ensure_case_open()
    elif status in {"completed", "ended", "call_ended"}:
        set_call_status(status, False)
        push({"type": "call_end"})
    elif status:
        STATE["call_status"] = status

    extracted = payload.get("extracted_data") or payload.get("dispositions") or {}
    field_map = {
        "name": "name",
        "home_state": "home_state",
        "city": "city",
        "trade": "trade",
        "language": "language",
    }
    for source_key, target_key in field_map.items():
        value = extracted.get(source_key)
        if value:
            set_case_field(target_key, value)

    transcript = payload.get("transcript")
    if isinstance(transcript, list):
        for turn in transcript:
            role = str(turn.get("role") or turn.get("speaker", "")).lower()
            who = "worker" if role in {"user", "human", "caller", "worker"} else "agent"
            text = turn.get("text") or turn.get("content") or ""
            add_transcript(who, text)
    elif isinstance(transcript, str):
        add_transcript("system", transcript)

    save_state()
    return {"ok": True}


# =====================================================================
# Wage complaint tool + demo flow
# =====================================================================
@app.post("/api/tools/file-complaint")
async def file_complaint(req: Request) -> dict[str, Any]:
    payload = await req.json()
    worker_name = payload.get("worker_name") or STATE["current_case"].get("name") or "Worker"
    contractor = payload.get("contractor", "—")
    amount = payload.get("amount")
    site = payload.get("site", "—")
    period = payload.get("period", "—")
    city = (
        payload.get("city")
        or STATE["current_case"].get("city")
        or STATE["current_case"].get("current_city")
    )
    complaint = update_wage_complaint(
        worker_name=worker_name,
        employer_name=contractor,
        amount=amount,
        site=site,
        period=period,
        city=city,
        days_unpaid=None,
        status="recorded_internal",
        reference_id=build_reference_id(demo=False),
    )
    save_state()
    return {
        "status": "recorded_internal",
        "reference_number": complaint["reference_id"],
        "next_step": (
            "Internal case record created. A real deployment would pass this to a verified legal escalation or labour helpline workflow."
        ),
    }


@app.post("/api/demo/seed")
def demo_seed() -> dict[str, Any]:
    reset_state(persist=False)
    set_call_status("demo_seeded", True)
    ensure_case_open(f"PD-{current_year()}-DEMO")
    set_case_field("name", "Ramesh Yadav")
    set_case_field("home_state", "Bihar")
    set_case_field("origin", "Bihar")
    set_case_field("city", "Bengaluru")
    set_case_field("trade", "construction helper")
    set_case_field("language", "Hindi")
    set_case_field("local_language_issue", "Kannada", field_id="lang")
    set_case_field("issues", "Unpaid wages and hospital language barrier")
    add_transcript(
        "worker",
        "Namaste Saathi, main Bihar se Bengaluru kaam ke liye aaya hoon.",
    )
    add_transcript(
        "agent",
        "Namaste bhai, main Saathi hoon. Aap aaram se batayein, main sun raha hoon.",
    )
    save_state()
    return state_snapshot()


@app.post("/api/demo/wage")
async def demo_wage() -> dict[str, Any]:
    if not STATE["current_case"].get("id"):
        demo_seed()
    add_transcript(
        "worker",
        "Mera 12 din ka paisa nahi mila. Thekedar kal bolke taal raha hai.",
    )
    add_transcript(
        "agent",
        "Samajh gaya. Main aapka case note kar raha hoon: shehar, kaam, din aur thekedar ka naam. Isse hum aage escalate karne layak record bana sakte hain.",
    )
    update_wage_complaint(
        worker_name=STATE["current_case"].get("name") or "Ramesh Yadav",
        employer_name="Sharma Constructions",
        amount="7200",
        site="Ward 42 housing site, Bengaluru",
        period="12 unpaid working days",
        city="Bengaluru",
        days_unpaid=12,
        status="drafted_demo",
        reference_id=build_reference_id(demo=True),
    )
    save_state()
    return state_snapshot()


# =====================================================================
# Health clip tool + demo flow
# =====================================================================
@app.post("/api/tools/health-clip")
async def health_clip(req: Request) -> dict[str, Any]:
    payload = await req.json()
    name = payload.get("worker_name", STATE["current_case"].get("name", "Worker"))
    card = await generate_health_card(
        worker_name=name,
        symptom_hindi=payload.get("symptom_hindi", ""),
        language_from="Hindi",
        language_to="Kannada",
    )
    STATE["health_card"] = card
    push({"type": "agent", "agent": "sehat"})
    push({"type": "clip", "data": card})
    save_state()
    return {
        "status": "created",
        "spoken_summary": (
            "Audio card ready. Tell the worker they can play it at the hospital counter."
        ),
    }


@app.post("/api/demo/health")
async def demo_health() -> dict[str, Any]:
    if not STATE["current_case"].get("id"):
        demo_seed()
    add_transcript(
        "worker",
        "Mere pet mein dard hai, hospital mein Kannada samajh nahi aa raha.",
    )
    add_transcript(
        "agent",
        "Theek hai. Main aapke liye Kannada mein ek chhota voice card bana raha hoon jo aap counter par suna sakte hain.",
    )
    card = await generate_health_card(
        worker_name=STATE["current_case"].get("name") or "Ramesh Yadav",
        symptom_hindi="Mere pet mein dard hai",
        language_from="Hindi",
        language_to="Kannada",
        text="ನನಗೆ ಹೊಟ್ಟೆ ನೋವು ಇದೆ. ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ತೋರಿಸಿ.",
        gloss="I have stomach pain. Please help me see a doctor.",
    )
    STATE["health_card"] = card
    push({"type": "agent", "agent": "sehat"})
    push({"type": "clip", "data": card})
    save_state()
    return state_snapshot()


# Cached demo card for self-running projector flow.
@app.get("/api/demo-card")
async def demo_card() -> dict[str, Any]:
    global DEMO_CARD
    if not DEMO_CARD:
        DEMO_CARD = await generate_health_card(
            worker_name="Ramesh Yadav",
            symptom_hindi="pet dard",
            language_from="Hindi",
            language_to="Kannada",
            text="ನನಗೆ ಹೊಟ್ಟೆ ನೋವು ಇದೆ. ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ತೋರಿಸಿ.",
            gloss="I have stomach pain. Please help me see a doctor.",
        )
    return DEMO_CARD


# =====================================================================
# Admin/localize + proactive follow-up
# =====================================================================
@app.post("/api/admin/localize")
async def admin_localize(req: Request) -> dict[str, Any]:
    body = await req.json()
    language = body.get("language", "ta")
    source_voice_id = body.get("source_voice_id") or hindi_voice()
    if not source_voice_id:
        return {"error": "No source voice id. Set CARTESIA_HINDI_VOICE_ID first."}
    try:
        voice = await cartesia_localize(source_voice_id, language, f"Saathi-{language}")
        voice_id = voice.get("id") or voice.get("voice_id")
        return {
            "status": "localized",
            "language": language,
            "voice_id": voice_id,
            "note": (
                "Put this in .env as CARTESIA_KANNADA_VOICE_ID (or per-language) and restart."
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/followup")
async def followup(req: Request) -> dict[str, Any]:
    body = await req.json()
    phone = body.get("phone")
    when = body.get("when", "now")
    when_label = "Now (live)"
    bolna_response: Any = {"status": "not_configured"}

    STATE["followup"] = {
        "name": STATE["current_case"].get("name", "Ramesh"),
        "phone": phone,
        "when": when_label,
        "created_at": now_iso(),
    }

    if bolna_configured() and phone:
        payload: dict[str, Any] = {
            "agent_id": os.environ["BOLNA_AGENT_ID"],
            "recipient_phone_number": phone,
            "user_data": {
                "worker_name": STATE["current_case"].get("name", "Ramesh"),
                "open_issue": STATE["current_case"].get("issues", "wage complaint"),
                "call_type": "followup",
            },
        }
        if when == "tomorrow_evening":
            timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            scheduled = (datetime.datetime.now(timezone) + datetime.timedelta(days=1)).replace(
                hour=18,
                minute=0,
                second=0,
                microsecond=0,
            )
            payload["scheduled_at"] = scheduled.isoformat()
            when_label = scheduled.strftime("Tomorrow 6:00 PM IST (scheduled via Bolna)")
            STATE["followup"]["when"] = when_label

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.bolna.ai/call",
                headers={
                    "Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        bolna_response = response.json() if response.status_code < 300 else response.text
    elif not phone:
        bolna_response = {"status": "missing_phone"}

    push({"type": "followup", "data": STATE["followup"]})
    save_state()
    return {"bolna_response": bolna_response}


@app.on_event("startup")
async def startup() -> None:
    global DEMO_CARD
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    load_state()
    try:
        DEMO_CARD = await generate_health_card(
            worker_name="Ramesh Yadav",
            symptom_hindi="pet dard",
            language_from="Hindi",
            language_to="Kannada",
            text="ನನಗೆ ಹೊಟ್ಟೆ ನೋವು ಇದೆ. ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ತೋರಿಸಿ.",
            gloss="I have stomach pain. Please help me see a doctor.",
        )
        LOGGER.info(
            "Demo card pre-warmed: %s",
            DEMO_CARD.get("audio_url") or "(text only — check Cartesia keys)",
        )
    except Exception as exc:
        LOGGER.warning("Demo card pre-warm skipped: %s", exc)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
