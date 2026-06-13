# PravaasiDesk

**The relocation desk every corporate employee gets — now one phone call away for India's migrant workers.**

A Hindi voice help-desk where a warm agent (*Saathi*) handles wage complaints, health, housing,
and paperwork over an ordinary phone call. Built on **Bolna** (voice orchestration) + **Cartesia**
(speech) for the VOC-A-Thon, Bengaluru.

## What's here

| File | Purpose |
|---|---|
| [`server.py`](server.py) | FastAPI glue: Bolna webhook → case state, custom tools (`file_wage_complaint`, `create_hospital_voice_card`), scheduled follow-up calls, Cartesia voice-card generation. |
| [`dashboard.html`](dashboard.html) | Projector "command center" — live case file, transcript, complaint stamp, Kannada voice card with word-synced karaoke captions. Includes a scripted demo fallback. |
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
pip install fastapi uvicorn httpx python-dotenv
cp .env.example .env   # then fill in keys (see SETUP.md)
python3 -m uvicorn server:app --reload --port 8000
ngrok http 8000        # Bolna needs a public URL for tools/webhooks
```

Open `dashboard.html` on the projector. Full instructions in [SETUP.md](SETUP.md).

---
Powered by Bolna + Cartesia.
