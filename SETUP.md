# PravaasiDesk — Bolna Agent Setup (Saathi)

## Agent identity (paste into Agent tab → Prompt)

```
You are Saathi, the voice of PravaasiDesk — a free relocation help desk for migrant
workers in India. You speak warm, simple Hindi (Devanagari). Short sentences. Never
corporate. Never rushed. The caller may be tired, worried, or new to the city.
Address them respectfully (aap, ji).

You are an orchestrator with a team of specialists, but the caller only ever hears
YOU. Never say "transferring" or name internal tools.

YOUR TEAM (invoke via tools):
- Haq (wages/rights): if caller mentions unpaid wages, thekedar fraud, or salary
  issues → collect: contractor name, amount owed (₹), work site, work period.
  Then call file_wage_complaint. Read back the reference number slowly, digit by
  digit, and say a notice will reach the contractor in 7 days.
- Sehat (health): if caller mentions illness or pain → reassure first. Name the
  nearest government hospital for their area (default: C.V. Raman General Hospital,
  Indiranagar for Bengaluru). Then call create_hospital_voice_card with their name
  and symptom. Tell them: "Maine ek audio bheja hai SMS par — hospital ke counter
  par bas isse chala dijiye."
- Basera (housing) and Kaagaz (paperwork like eShram, bank account, ration card):
  give one concrete next step from your knowledge, keep it simple. (No tool yet.)

EVERY FIRST CALL: naturally collect name, home district/state, current city, and
trade (work type) within the conversation — do not interrogate, weave it in.

ALWAYS end the call with: "Kal shaam main khud phone karke poochhunga ki sab theek
raha ya nahin. Aap akele nahin hain." Then wish them well.

FOLLOW-UP CALLS (when {call_type} == "followup"): you already know {worker_name}
and {open_issue}. Open with: "Namaste {worker_name} ji, PravaasiDesk se Saathi bol
raha hoon. Kal aapne {open_issue} ke baare mein bataya tha — kya update hai?"
React to their answer, close warmly.

SAFETY: If the caller describes an emergency (severe chest pain, accident, violence),
tell them to call 112 immediately before anything else.
```

## Welcome message (Agent tab)
```
नमस्ते! प्रवासी डेस्क में आपका स्वागत है। मैं साथी हूँ। बताइए, क्या मदद चाहिए?
```

## Tab-by-tab config

| Tab | Setting |
|---|---|
| **Audio** | Language: Hindi (enable Bolna's language-switch if you want Hinglish). TTS: select **Cartesia** as provider, pick a warm male/female Hindi voice → **copy its voice id into `.env` as `CARTESIA_HINDI_VOICE_ID`** (this is the voice the caller hears AND the voice that speaks the Kannada card). STT: default (test Hindi accuracy first thing). |
| **LLM** | Claude (Opus/Sonnet) for reliable tool-calling. Temperature low (0.3). **Attach a Knowledge Base** (see below) so Kaagaz/Basera answer from real scheme docs. |
| **Tools** | Two custom API tools → your ngrok URL:<br>`file_wage_complaint` → POST `https://<ngrok>/api/tools/file-complaint`<br>`create_hospital_voice_card` → POST `https://<ngrok>/api/tools/health-clip`<br>(Parameter schemas are in server.py comments.) |
| **Analytics** | Webhook URL: `https://<ngrok>/webhook/bolna`. Add extraction dispositions: name, home_state, city, trade, language. Enable transcript streaming if your plan supports it. |
| **Inbound** | Provision/buy a number and **assign this agent to it** — put that number on the projector so the audience can call live. |
| **Call** | Telephony default. Enable interruption handling. |

## .env file

```
BOLNA_API_KEY=bn-xxxx
BOLNA_AGENT_ID=<agent id>
CARTESIA_API_KEY=sk_car_xxxx
CARTESIA_HINDI_VOICE_ID=<Saathi's Hindi voice id from the Audio tab>
# Optional: a dedicated/localized Kannada voice. If unset, the card is rendered with the
# Hindi voice id at language=kn → "Saathi's own voice speaks Kannada" (recommended path).
CARTESIA_KANNADA_VOICE_ID=
PUBLIC_BASE_URL=https://<ngrok>      # so the SMS audio link / dashboard clip resolves
ANTHROPIC_API_KEY=sk-ant-xxxx        # optional: Hindi→Kannada symptom translation fallback
```

## Knowledge Base / RAG (Bolna → LLM tab)
Ingest 2–3 real scheme PDFs so paperwork/housing advice is grounded, not hallucinated:
eShram registration, ration-card portability (ONORC), PM-JAY (Ayushman) eligibility.
Then tighten the prompt: "For Kaagaz/Basera questions, answer ONLY from the knowledge base."

## Cartesia standouts (what makes us stand out beyond the mandatory voice)
- **Saathi's own voice speaks Kannada** — the hospital card is generated with the *same*
  Cartesia voice id at `language=kn` (multilingual TTS). Same comforting voice that helped
  Ramesh in Hindi now speaks for him at the counter. (Cartesia *Localize* supports hi/ta/te
  but not kn yet — `POST /api/admin/localize {"language":"ta"}` mints a localized voice for
  those; the Kannada card uses direct multilingual TTS, same narrative, less risk.)
- **Word-timestamp karaoke captions** — `health_clip` calls Cartesia `/tts/sse` with
  `add_timestamps`, returns `words[]`, and the dashboard highlights each Kannada word in sync
  with the audio on the projector. Falls back to `/tts/bytes` + even timing if SSE hiccups.

## Proactive follow-up (real, not a button)
`POST /api/followup {"phone":"+91...","when":"tomorrow_evening"}` uses Bolna's native
`scheduled_at` to genuinely book the call for tomorrow 6 PM IST. Use `"when":"now"` to ring
your phone live on stage.

## Demo-day flow
1. `uvicorn server:app --port 8000` + `ngrok http 8000`
2. Open `dashboard.html` on the projector.
3. Call your Bolna agent's number live. Play Ramesh. Dashboard fills in real time via webhooks/tools.
4. After hanging up, hit `POST /api/followup` with your phone number — **your phone rings on stage**. Answer on speaker.
5. If anything breaks: hit "Run demo sequence" — the scripted fallback is indistinguishable in pacing.

## Hour-by-hour (tomorrow)
| Hr | Do |
|---|---|
| 0–1 | Bolna account, agent created with prompt above, test call in playground. Cartesia key + pick voice. |
| 1–2 | server.py running + ngrok + webhook firing → dashboard fields populate from a real call |
| 2–3.5 | file_wage_complaint tool wired; rehearse the wage conversation till extraction is clean |
| 3.5–5 | health-clip tool + Cartesia Kannada clip plays from dashboard (verify `kn` support; fallback: Hindi clip + Kannada text on screen) |
| 5–6 | /api/followup outbound call works; tune followup prompt |
| 6–7 | Voice tuning (warmth, speed), dashboard polish, edge cases |
| 7–8 | Two full rehearsals + record backup video of demo mode |

## Known risks & fallbacks
- **Cartesia Kannada** → `kn` TTS *is* supported (the card works); only the *Localize* endpoint lacks `kn`, so we use direct multilingual TTS with the Hindi voice id. Fallback if TTS fails: the dashboard still shows the Kannada text card + karaoke (even timing) with no audio.
- **Pre-stage the voice once**: confirm `CARTESIA_HINDI_VOICE_ID` is set; (optional) `POST /api/admin/localize {"language":"ta"}` to demo Localize for a supported language.
- **Bolna webhook only fires post-call on some plans** → dashboard updates after hangup instead of live; restructure demo: call first, then walk through populated case file.
- **Tool-call latency on stage** → keep tool responses short (they're spoken context); pre-warm with a test call before demo slot.
- **STT mishears Bhojpuri** → stick to clear Hindi in the live demo; mention Bhojpuri as roadmap.
