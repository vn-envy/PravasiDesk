# PravaasiDesk Setup

This guide is the practical path to a working judge demo.

## Step 1: install and run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn server:app --reload --port 8000
```

Open these locally:

- `http://localhost:8000/`
- `http://localhost:8000/demo`
- `http://localhost:8000/healthz`

Run the readiness checks:

```bash
python3 evals.py --base-url http://localhost:8000
```

## Step 2: expose with ngrok for local testing

Bolna needs a public URL for webhooks and custom tool calls.

```bash
ngrok http 8000
```

Take the HTTPS forwarding URL from ngrok and set:

```env
PUBLIC_BASE_URL=https://your-ngrok-subdomain.ngrok-free.app
```

Restart the server after changing `.env`.

## Step 3: configure Bolna webhooks and tools

Set these env vars:

```env
BOLNA_API_KEY=
BOLNA_AGENT_ID=
BOLNA_PHONE_NUMBER=
```

Configure Bolna to call these backend routes:

- Webhook URL: `{PUBLIC_BASE_URL}/webhook/bolna`
- Custom tool `file_wage_complaint`: `{PUBLIC_BASE_URL}/api/tools/file-complaint`
- Custom tool `create_hospital_voice_card`: `{PUBLIC_BASE_URL}/api/tools/health-clip`
- Follow-up workflow endpoint: `{PUBLIC_BASE_URL}/api/followup`

Recommended agent behaviour:

- Collect worker name, origin, city, work type, and language naturally.
- When unpaid wages are reported, trigger the wage complaint tool.
- When hospital language help is needed, trigger the health clip tool.

## Step 4: configure Cartesia voice IDs

Set these env vars:

```env
CARTESIA_API_KEY=
CARTESIA_HINDI_VOICE_ID=
CARTESIA_KANNADA_VOICE_ID=
CARTESIA_MODEL_ID=sonic-2
CARTESIA_VERSION=2024-11-13
```

Notes:

- `CARTESIA_HINDI_VOICE_ID` is Saathi’s main spoken voice.
- `CARTESIA_KANNADA_VOICE_ID` is used for the hospital voice card if provided.
- If Cartesia keys or voice IDs are missing, the judge demo still works with a text-only fallback card.

Optional:

```env
ANTHROPIC_API_KEY=
JUDGE_DEMO_PIN=
DEMO_MODE=true
STATE_FILE=demo_state.json
```

## Step 5: deploy to Render

1. Push the repo to GitHub.
2. In Render, create a new Web Service or use the included Blueprint from `render.yaml`.
3. Set all required env vars from `.env.example`.
4. Deploy the service.
5. Confirm these public URLs respond:
   - `/demo`
   - `/healthz`
   - `/api/state`

## Step 6: final smoke test

Run these checks against the final environment:

```bash
python3 evals.py --base-url https://your-render-service.onrender.com
```

Manual judge flow:

1. Open `/demo`
2. Click `Seed Judge Demo`
3. Click `Run Wage Case`
4. Click `Run Hospital Voice Card`
5. Optional live voice line through Bolna:
   - `Saathi, mera 12 din ka paisa nahi mila.`
   - `Mere pet mein dard hai, hospital mein Kannada samajh nahi aa raha.`

Expected result:

- `/healthz` shows the backend is healthy
- `/api/config/public` exposes only safe public config
- the dashboard updates via polling
- the wage panel fills in after the wage action
- the hospital card shows Kannada text, with audio only if Cartesia is configured
