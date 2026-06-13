#!/usr/bin/env python3
"""
PravaasiDesk pre-flight evals — run these before the live demo to confirm the
Bolna + Cartesia stack is wired correctly.

Usage:
    # 1. Start the server in another terminal:
    #    python3 -m uvicorn server:app --port 8000
    # 2. Run the evals:
    python3 evals.py            # safe pre-flight (no real phone call)
    python3 evals.py --live     # also places a REAL outbound call to TEST_PHONE

Env (.env or shell):
    EVAL_BASE      where the server is reachable        (default http://localhost:8000)
    TEST_PHONE     your phone in E.164 for the --live call (e.g. +9198XXXXXXXX)

Exit code 0 = all required checks passed (you're good to run).
"""
import os, sys, glob, time
import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = os.environ.get("EVAL_BASE", "http://localhost:8000").rstrip("/")
LIVE = "--live" in sys.argv
TEST_PHONE = os.environ.get("TEST_PHONE", "")

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"
results = []  # (name, status)  status in {PASS, FAIL, WARN, SKIP}

def record(name, status, detail=""):
    icon = {"PASS": f"{G}✓ PASS{X}", "FAIL": f"{R}✗ FAIL{X}",
            "WARN": f"{Y}~ WARN{X}", "SKIP": f"{B}· SKIP{X}"}[status]
    print(f"  {icon}  {name}")
    if detail:
        for line in detail.splitlines():
            print(f"          {line}")
    results.append((name, status))

def get_state():
    return httpx.get(f"{BASE}/api/state", timeout=10).json()

print(f"\n{B}PravaasiDesk evals{X}  →  {BASE}   (mode: {'LIVE' if LIVE else 'pre-flight'})\n")

# ── E1 — server reachable ────────────────────────────────────────────────────
try:
    httpx.post(f"{BASE}/api/reset", timeout=10).raise_for_status()
    get_state()
    record("E1  Server reachable & responding", "PASS")
except Exception as e:
    record("E1  Server reachable & responding", "FAIL",
           f"Can't reach {BASE}. Start it: python3 -m uvicorn server:app --port 8000\n{e}")
    print(f"\n{R}Server down — aborting.{X}\n")
    sys.exit(1)

# ── E2 — wage complaint tool (logic, no external deps) ───────────────────────
try:
    r = httpx.post(f"{BASE}/api/tools/file-complaint", timeout=15, json={
        "worker_name": "Ramesh Yadav", "contractor": "Suresh",
        "amount": "4,500", "site": "Whitefield, Prestige site", "period": "19 May - 8 Jun"}).json()
    ref = r.get("reference_number", "")
    import re
    ok_ref = bool(re.match(r"^SS/KA/2026/[A-Z0-9]{5}$", ref))
    evs = get_state()["events"]
    has_complaint = any(e["type"] == "complaint" and e["data"]["contractor"] == "Suresh" for e in evs)
    has_agent = any(e["type"] == "agent" and e.get("agent") == "haq" for e in evs)
    if ok_ref and has_complaint and has_agent:
        record("E2  Wage complaint tool → ref + dashboard event", "PASS", f"ref = {ref}")
    else:
        record("E2  Wage complaint tool → ref + dashboard event", "FAIL",
               f"ref_ok={ok_ref} complaint_event={has_complaint} haq_routed={has_agent}")
except Exception as e:
    record("E2  Wage complaint tool → ref + dashboard event", "FAIL", str(e))

# ── E3 — Cartesia voice card: audio + word timestamps (HEADLINE) ─────────────
try:
    before = set(glob.glob("static/clip_*"))
    httpx.post(f"{BASE}/api/tools/health-clip", timeout=60, json={
        "worker_name": "Ramesh", "symptom_hindi": "pet dard"})
    clip = next(e["data"] for e in reversed(get_state()["events"]) if e["type"] == "clip")
    kn_ok = "ಹೊಟ್ಟೆ" in clip["kannada_text"]  # dict translation of "pet dard"
    audio_ok = bool(clip.get("audio_url"))
    words = clip.get("words") or []
    # confirm a real, non-trivial audio file landed on disk (.wav from SSE, .mp3 from fallback)
    new = [f for f in glob.glob("static/clip_*") if f not in before]
    mp3_ok = bool(new) and os.path.getsize(new[-1]) > 1500

    if not kn_ok:
        record("E3  Cartesia Kannada voice card", "FAIL",
               "Kannada text malformed — check symptom translation.")
    elif audio_ok and mp3_ok and words:
        record("E3  Cartesia Kannada voice card (audio + karaoke timestamps)", "PASS",
               f"mp3={os.path.basename(new[-1])} ({os.path.getsize(new[-1])//1024} KB), "
               f"{len(words)} word timestamps → karaoke will sync to audio")
    elif audio_ok and mp3_ok and not words:
        record("E3  Cartesia voice card — audio OK, timestamps missing", "WARN",
               "Audio generated but /tts/sse returned no word_timestamps (fell back to /tts/bytes).\n"
               "Karaoke still works via even timing. To fix: bump CARTESIA_VERSION or check add_timestamps support.")
    else:
        record("E3  Cartesia voice card", "FAIL",
               "No audio produced — set CARTESIA_API_KEY and CARTESIA_HINDI_VOICE_ID in .env.\n"
               "(Dashboard still shows the Kannada text + timed karaoke as a fallback.)")
except Exception as e:
    record("E3  Cartesia voice card", "FAIL", str(e))

# ── E4 — Bolna webhook → case file (extraction + live transcript) ────────────
try:
    httpx.post(f"{BASE}/api/reset", timeout=10)
    httpx.post(f"{BASE}/webhook/bolna", timeout=15, json={
        "status": "started",
        "extracted_data": {"name": "Ramesh Yadav", "home_state": "Gorakhpur, UP",
                           "city": "Bengaluru", "trade": "Mason", "language": "Hindi"},
        "transcript": [{"role": "user", "text": "namaste, meri madad kijiye"},
                       {"role": "agent", "text": "namaste ji, bataiye"}]})
    s = get_state()
    fields_ok = s["case"].get("name") == "Ramesh Yadav" and s["case"].get("city") == "Bengaluru"
    tr = [e for e in s["events"] if e["type"] == "transcript"]
    tr_ok = len(tr) >= 2 and any(e["who"] == "worker" for e in tr) and any(e["who"] == "agent" for e in tr)
    if fields_ok and tr_ok:
        record("E4  Bolna webhook → case file + live transcript", "PASS",
               f"case fields: {list(s['case'].keys())}, transcript turns: {len(tr)}")
    else:
        record("E4  Bolna webhook → case file + live transcript", "FAIL",
               f"fields_ok={fields_ok} transcript_ok={tr_ok}")
except Exception as e:
    record("E4  Bolna webhook → case file + live transcript", "FAIL", str(e))

# ── E5 — Bolna outbound call (config presence; real ring only with --live) ───
bolna_key = os.environ.get("BOLNA_API_KEY", "")
bolna_agent = os.environ.get("BOLNA_AGENT_ID", "")
if not (bolna_key and bolna_agent):
    record("E5  Bolna outbound call config", "FAIL",
           "Set BOLNA_API_KEY and BOLNA_AGENT_ID in .env.")
elif not LIVE:
    record("E5  Bolna outbound call config present", "PASS",
           "Keys set. Run `python3 evals.py --live` (with TEST_PHONE set) to place a real call.")
elif not TEST_PHONE:
    record("E5  Bolna outbound call (live)", "SKIP",
           "Set TEST_PHONE=+91… to ring your phone in --live mode.")
else:
    try:
        r = httpx.post(f"{BASE}/api/followup", timeout=30,
                       json={"phone": TEST_PHONE, "when": "now"})
        body = r.json().get("bolna_response", {})
        txt = str(body).lower()
        ok = isinstance(body, dict) and ("queued" in txt or "execution" in txt or body.get("status"))
        if ok:
            record("E5  Bolna outbound call placed (your phone should ring)", "PASS",
                   f"bolna: {body}")
        else:
            record("E5  Bolna outbound call placed", "FAIL",
                   f"Unexpected Bolna response: {body}")
    except Exception as e:
        record("E5  Bolna outbound call placed", "FAIL", str(e))

# ── summary ──────────────────────────────────────────────────────────────────
n_pass = sum(1 for _, s in results if s == "PASS")
n_fail = sum(1 for _, s in results if s == "FAIL")
n_warn = sum(1 for _, s in results if s == "WARN")
print(f"\n{B}── summary ──{X}  {G}{n_pass} pass{X}  {Y}{n_warn} warn{X}  {R}{n_fail} fail{X}")
if n_fail == 0:
    print(f"{G}READY TO RUN.{X}  Place a live call to your inbound number and watch the dashboard.\n")
    sys.exit(0)
else:
    print(f"{R}Not ready — fix the FAILs above.{X}\n")
    sys.exit(1)
