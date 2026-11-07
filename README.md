# 📞 Hinglish Voice Receptionist

**An AI receptionist that answers a small business's phone in Hindi, English or Hinglish. It books appointments, answers questions and sends a WhatsApp confirmation, so no customer call goes unanswered.**

> 🚧 **Status:** in development. See [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) for progress.

![tests](https://img.shields.io/badge/tests-pytest-blue) ![python](https://img.shields.io/badge/python-3.11-blue) ![license](https://img.shields.io/badge/license-MIT-green)

---

## Why this exists

Small clinics, salons and coaching centres in India lose customers to missed calls, because the one person at the front desk is also handling walk-ins. Most voice bots struggle with Indian accents, with people switching between Hindi and English mid-sentence, with silence on the line and with slow replies.

This project is built for how people actually talk:

```
📞 Caller : Hello, kal shaam ko cleaning ka slot milega?
🤖 Bot    : Haan ji! Kal saade paanch aur chhe baje slot free hai. Kaunsa book karoon?
📞 Caller : Saade paanch theek hai.
🤖 Bot    : Aapka naam bata dijiye?
📞 Caller : Ravi.
🤖 Bot    : Ravi ji, kal saade paanch baje cleaning book ho gayi. WhatsApp par confirmation bhej diya hai.

💬 WhatsApp → "✅ Appointment confirmed: Mehta Dental, Tue 10 Nov, 5:30 PM"
```

## Features

- 🗣️ **Hinglish-first conversation**: understands and replies in Hindi, English or a mix, including language switches mid-sentence
- 📅 **Appointment booking**: check slots, book, cancel and reschedule, with double-booking protection
- 📒 **FAQ answers from the business's own notes (RAG)**: fees, timings and location; it says "I'll confirm with staff" instead of guessing
- 💬 **WhatsApp confirmations and reminders** through the WhatsApp Cloud API
- 🗓️ **Google Calendar sync**: bookings appear in the clinic's calendar, and manually blocked times are respected
- ⚡ **Low-latency streaming voice**: barge-in (the caller can interrupt), silence handling, and filler phrases for slow lookups
- 🙋 **Human handoff**: forwards the call or takes a message
- 📊 **Owner dashboard**: appointments, call transcripts, unanswered questions and stats

## How it works

```
Caller ──phone──▶ Twilio / Plivo ──audio stream──▶ Pipecat pipeline
                                                     │
              ┌──────────────────────────────────────┼──────────────────────────────┐
              ▼                                      ▼                              ▼
     Silero VAD + Sarvam STT  ──text──▶  LLM agent + tools  ──text──▶  Sarvam TTS (Bulbul)
        (ears)                            (brain)  │                      (mouth)
                                                   ├── check_slots / book / cancel / reschedule ─▶ SQLite ⇄ Google Calendar
                                                   ├── answer_faq ─▶ Chroma (FAQ RAG)
                                                   ├── send WhatsApp ─▶ WhatsApp Cloud API
                                                   └── transfer_to_human
                                                                   │
                                          Call logs + metrics ─▶ Streamlit dashboard
```

1. **Listen:** voice activity detection notices when the caller stops speaking, and Sarvam STT turns the audio into text.
2. **Think:** the LLM understands the request and calls tools. Slots, prices and timings **only** come from tools and the clinic's data, never from the model's imagination.
3. **Speak:** the reply is streamed sentence by sentence to Sarvam TTS and played back to the caller.
4. **Follow up:** bookings sync to Google Calendar and trigger a WhatsApp confirmation in the background.

For a non-technical walkthrough with diagrams, open [`docs/hinglish-voice-receptionist-explained.html`](docs/hinglish-voice-receptionist-explained.html).

## Tech stack

| Layer | Choice |
|---|---|
| Voice pipeline | [Pipecat](https://github.com/pipecat-ai/pipecat) |
| Speech-to-Text / LLM / Text-to-Speech | [Sarvam AI](https://sarvam.ai) (Saaras, Sarvam-105B, Bulbul) |
| Voice activity detection | Silero VAD |
| Telephony | Twilio (demo) → Plivo / Exotel (Indian number) |
| Backend | FastAPI, SQLModel + SQLite |
| FAQ retrieval | Chroma |
| Messaging | WhatsApp Cloud API |
| Calendar | Google Calendar API |
| Dashboard | Streamlit |
| Deploy | Docker Compose + Cloudflare Tunnel |
| Testing | pytest, respx, golden Hinglish evals |

## Quick start

### 1. Prerequisites
- Python 3.11+
- API keys: Sarvam AI, Meta WhatsApp Cloud API (test number), Google Cloud service account (Calendar API), Twilio (trial)

### 2. Install
```bash
git clone https://github.com/<your-username>/hinglish-receptionist.git
cd hinglish-receptionist
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then fill in your keys
```

### 3. Add your business details
Edit `data/clinic.yaml` (name, hours, services, slot length) and `data/faqs.md` (common questions), then:
```bash
python scripts/ingest_faqs.py
```

### 4. Try it
```bash
python scripts/chat_cli.py                 # chat by typing
uvicorn app.server:app --reload            # API + voice server
streamlit run dashboard/streamlit_app.py   # owner dashboard
```
To talk by voice, open the browser client served by the voice bot (see `docs/architecture.md`). For phone calls, expose the server with `cloudflared tunnel --url http://localhost:8000` and set your Twilio number's voice webhook to `https://<tunnel>/twilio/voice`.

### 5. Run with Docker
```bash
docker compose up --build
```

## Configuration

All settings come from environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | Sarvam STT, LLM and TTS |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` | Phone calls |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` | WhatsApp messages and webhook |
| `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_CALENDAR_ID` | Calendar sync |
| `PUBLIC_BASE_URL` | Public URL for webhooks |
| `DASHBOARD_PASSWORD` | Dashboard login |
| `DAILY_BUDGET_INR` | Spend alert threshold |

## Testing

```bash
pytest                       # offline suite: unit + integration, all APIs mocked (< 30 s)
pytest -m live               # real API tests (costs a few paise)
python scripts/run_evals.py  # golden Hinglish conversations against the real LLM
python scripts/latency_report.py
```

- **Unit tests:** slot logic, Hinglish time parsing ("kal shaam saade paanch" → 17:30 tomorrow), phone normalisation, speech formatting.
- **Integration tests:** the agent with a fake LLM, WhatsApp/Calendar failures, barge-in, silence handling, Twilio webhooks.
- **Evals:** every case in `data/test_calls.yaml` is checked for the correct tool call, **zero hallucinated slots**, the reply language and the reply length.

## Results

> Filled in from `reports/` as phases complete.

| Metric | Target | Current |
|---|---|---|
| Booking success on real calls | ≥ 90% | TBD |
| Hallucinated slots / fees | 0 | TBD |
| Turn latency p50 / p95 (phone) | ≤ 2 s / ≤ 3 s | TBD |
| Eval pass rate | ≥ 90% | TBD |
| FAQ retrieval top-3 accuracy | ≥ 90% | TBD |
| AI cost per call minute | ≤ ₹1.5 | TBD |

## Project structure

```
app/          core: booking, timeparse, tools, agent, prompts, rag, whatsapp,
              calendar_sync, voice_bot, server, metrics
dashboard/    Streamlit owner dashboard
data/         clinic.yaml, faqs.md, test_calls.yaml
tests/        unit/, integration/, evals/, fixtures/
scripts/      chat CLI, FAQ ingest, evals, latency report, smoke test
docs/         BUILD_PLAN.md, architecture.md, telephony.md, explainer page
reports/      eval and latency reports
```

## Cost

Built to run on a student budget (≤ ₹800 to build and demo):

| Item | Approx. cost |
|---|---|
| Sarvam STT | ₹30 / hour of audio |
| Sarvam TTS | ₹15–30 / 10K characters |
| Sarvam-105B LLM | ₹4 input / ₹16 output per 1M tokens |
| WhatsApp utility message (India) | ~₹0.12 (test number free) |
| Calendar, Chroma, tunnel, Pipecat | Free |
| Hosting | Free-tier VM or ~₹300–400 / month |

That works out to roughly **₹1–1.5 per minute of conversation**. Prices are as of Nov 2026 and may change.

## Roadmap

See [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) for the full phase-by-phase plan.

- [ ] Booking engine + text agent
- [ ] FAQ RAG
- [ ] Browser voice + latency hardening
- [ ] WhatsApp + Google Calendar
- [ ] Phone calls
- [ ] Dashboard + deployment
- [ ] Pilot with a local clinic in Udaipur
- [ ] More Indian languages (Marathi, Gujarati, Tamil)
- [ ] Multi-business support

## Known limitations

- A real Indian phone number needs business KYC, so it's registered under the pilot business's documents. The demo uses a Twilio trial number.
- Heavy background noise and very poor network connections reduce speech-recognition accuracy.
- Not for medical advice. The bot only handles scheduling and general clinic information.

## Contributing

Issues and pull requests are welcome. Please run `ruff check . && pytest` before opening a PR. Contributors using Claude Code should read [`CLAUDE.md`](CLAUDE.md).

## License

MIT

## Author

**Akshat Jain** · B.Tech AI & Data Science, CTAE Udaipur
GenAI / LLM engineering: RAG, agents, voice agents
