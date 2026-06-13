# PravaasiDesk

**The relocation desk every corporate employee gets — now one phone call away for India's migrant workers.**

A Hindi voice help-desk where a warm agent (*Saathi*) handles wage complaints, health, housing,
and paperwork over an ordinary phone call. Built on **Bolna** (voice orchestration) + **Cartesia**
(speech) for the VOC-A-Thon, Bengaluru.

This repo keeps the original **FastAPI + `dashboard.html`** architecture and now adds a
judge-demo path with persisted state, health/config endpoints, and demo seed flows.

## Live Judge Demo Setup

### Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn server:app --reload --port 8000
```

Run the readiness checks:

```bash
python3 evals.py --base-url http://localhost:8000
```

### Render deployment

1. Push this repo to GitHub.
2. In Render, create a new Web Service or use the included `render.yaml` Blueprint.
3. Set the required environment variables from `.env.example`.
4. Deploy and confirm `GET /healthz` returns `ok: true`.
5. Open the public `/demo` URL on the projector.

### Required env vars

```env
DEMO_MODE=true
PUBLIC_BASE_URL=http://localhost:8000
STATE_FILE=demo_state.json
BOLNA_API_KEY=
BOLNA_AGENT_ID=
BOLNA_PHONE_NUMBER=
CARTESIA_API_KEY=
CARTESIA_HINDI_VOICE_ID=
CARTESIA_KANNADA_VOICE_ID=
CARTESIA_MODEL_ID=sonic-2
CARTESIA_VERSION=2024-11-13
ANTHROPIC_API_KEY=
JUDGE_DEMO_PIN=
```

### Public URLs

- `/demo`
- `/healthz`
- `/api/state`

### Bolna setup

- Webhook URL: `{PUBLIC_BASE_URL}/webhook/bolna`
- Custom function file complaint: `{PUBLIC_BASE_URL}/api/tools/file-complaint`
- Custom function health clip: `{PUBLIC_BASE_URL}/api/tools/health-clip`
- Follow-up endpoint: `{PUBLIC_BASE_URL}/api/followup`

### Cartesia setup

- Configure `CARTESIA_API_KEY`
- Configure `CARTESIA_HINDI_VOICE_ID` and `CARTESIA_KANNADA_VOICE_ID`
- If Cartesia keys or voice IDs are missing, the hospital demo still passes using the text-only fallback card

### Judge script

1. Open `/demo`
2. Click `Seed Judge Demo`
3. Click `Run Wage Case`
4. Click `Run Hospital Voice Card`
5. Optional: call the Bolna number and say:
   `Saathi, mera 12 din ka paisa nahi mila.`
   `Mere pet mein dard hai, hospital mein Kannada samajh nahi aa raha.`

## What's here

| File | Purpose |
|---|---|
| [`server.py`](server.py) | FastAPI glue: Bolna webhook → case state, custom tools (`file_wage_complaint`, `create_hospital_voice_card`), scheduled follow-up calls, Cartesia voice-card generation. |
| [`dashboard.html`](dashboard.html) | Projector "command center" served by the backend at `/` and `/demo`. Uses live state plus judge-demo endpoints, with an offline fallback. |
| [`evals.py`](evals.py) | Pre-flight checks for `/healthz`, `/api/config/public`, `/api/demo/*`, existing tools, and webhook compatibility. |
| [`SETUP.md`](SETUP.md) | Bolna agent prompt, tab-by-tab config, `.env` template, and the demo runbook. |

## Standout features (beyond the mandatory Cartesia voice)

- **Saathi's own voice speaks Kannada** — the hospital voice card is rendered with the *same*
  Cartesia voice the caller hears, at `language=kn`. The voice that comforted the worker in Hindi
  now speaks for them at the hospital counter.
- **Word-timestamp karaoke captions** — `/tts/sse` with `add_timestamps` drives word-by-word
  highlighting of the Kannada card, synced to the audio on the projector.
- **Real proactive follow-up** — Bolna's native `scheduled_at` genuinely books a callback for the
  next evening — "main khud phone karunga" made true, not a button.
- **Knowledge-base grounded advice** + real inbound number (Bolna platform config).

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn server:app --reload --port 8000
ngrok http 8000        # Bolna needs a public URL for tools/webhooks
```

Open [http://localhost:8000/](http://localhost:8000/) or [http://localhost:8000/demo](http://localhost:8000/demo) on the projector. Full instructions in [SETUP.md](SETUP.md).

## Judge demo endpoints

- `GET /healthz`
- `GET /api/config/public`
- `POST /api/demo/seed`
- `POST /api/demo/wage`
- `POST /api/demo/health`
- `POST /api/reset`

---
Powered by Bolna + Cartesia.
