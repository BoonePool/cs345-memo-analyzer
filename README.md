# Voice Form Assistant (CS 345 / CSC 645, Fall 2026)

A Flask service for people who cannot easily type. The user speaks their answers,
the app transcribes them with Azure AI Speech, extracts form fields with Azure AI
Language, and asks for whatever is still missing. Later parts add read-back by
neural TTS, a frontend, App Service deployment and telemetry to Application Insights.

Built on the Voice Memo Analyzer reference design. The original memo pipeline is in
the git history before the `voice-form-assistant` branch.

## Status

| Part | Description | State |
|------|-------------|-------|
| A | Azure provisioning (Speech, Language, Log Analytics, App Insights) | Done — `provision_part_a.sh` |
| B | `POST /transcribe` — continuous recognition, word-level confidence, HTTP 415 on bad audio | Done — `speech_service.py` |
| C | Form field extraction — name, date, request type; multi-turn sessions | Done — `language_service.py`, `form_schema.py`, `session.py` |
| D–G | Confirmation read-back (TTS), frontend, App Service deployment, telemetry | Not started |

## Architecture

```
client ──audio or text──▶ POST /form/turn ──▶ Speech (Part B) ──▶ transcript
                               │                                     │
                               │                          Language NER: Person, DateTime
                               │                          keyword rules: request type
                               ▼                                     │
                     FormSession (in memory) ◀── fill missing fields only
                               │
                               ▼
                 { fields, missing, next_question, confirmation_text }
```

- `app.py` — Flask entry point and routes. Loads `.env` before importing the SDKs.
- `speech_service.py` — `transcribe_file()`: continuous recognition, parses per-word timings
  from the detailed JSON, maps SDK format errors to HTTP 415.
- `form_schema.py` — the form: fields, question wording, field order, allowed request types.
- `language_service.py` — `extract_fields()`: Person and DateTime entities from Azure AI
  Language; `normalize_date()` resolves "tomorrow", "next Tuesday", and "March 3" (rolled to
  next year when no year is spoken) against today's date.
- `session.py` — in-memory `FormSession` store with a 30-minute idle expiry. Records which
  fields were filled from speech and which were corrected, for the Part G metric.
- Uploaded audio is written to `temp_audio/` and deleted in a `finally` block.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/form/start` | Create a session. Returns the state with the first question. |
| POST | `/form/turn` | One answer. Multipart `audio` (WAV/MP3) or JSON `{"text"}`, plus optional `session_id`. Fills only missing fields. |
| POST | `/form/correct` | JSON `{session_id, field, value}`. Manual fix; counts against first-try accuracy. |
| POST | `/form/confirm` | JSON `{session_id}`. Submits once all fields are filled. |
| GET | `/form/<session_id>` | Current state. |
| POST | `/transcribe` | Part B: audio in, transcript and word timings out. |

State responses include `fields` (value, display text, source, `first_try`), `missing`,
`next_question`, and `confirmation_text`, which is the sentence to read back.

Error responses: `400` missing input or invalid value, `404` unknown session,
`409` form not complete or already submitted, `413` file over 25 MB, `415` unsupported
file or audio the Speech SDK cannot decode, `500` Speech error, `502` Language error.

## Setup

Requires Python 3.11+ (developed on 3.14) and the Azure CLI.

```bash
# 1. Provision Azure resources (Part A) and write .env
az login
./provision_part_a.sh

# 2. Install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run locally (macOS reserves port 5000 for AirPlay, so use another port)
PORT=5050 .venv/bin/python app.py
```

Copy `.env.example` to `.env` if you are not using the provisioning script.
`.env` is git-ignored and must never be committed.

### Region note

The subscription has an "Allowed resource deployment regions" policy. Speech, Language
and Log Analytics were rejected in `eastus` and `eastus2`, so all resources are in
`northcentralus`. `AZURE_SPEECH_REGION` must match.

## Example session

```bash
SID=$(curl -s -X POST http://localhost:5050/form/start | python3 -c "import json,sys;print(json.load(sys.stdin)['session_id'])")

# Spoken answer (any mix of the three fields)
curl -X POST -F "session_id=$SID" -F "audio=@tests/audio/form_turn1.wav" http://localhost:5050/form/turn

# Or typed
curl -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"text\":\"Tomorrow please.\"}" http://localhost:5050/form/turn

# Fix a field, then submit
curl -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SID\",\"field\":\"date\",\"value\":\"2026-11-25\"}" http://localhost:5050/form/correct
curl -X POST -H "Content-Type: application/json" -d "{\"session_id\":\"$SID\"}" http://localhost:5050/form/confirm
```

## Limitations

- **Request type uses keyword rules**, not a trained model. It covers the phrases in
  `form_schema.py` and will miss paraphrases. A custom classifier or a Foundry model with a
  JSON schema prompt would be the next step. Check the tier and cost before adopting either.
- **Name extraction relies on prebuilt Person entities**, so it can miss unusual names or
  pick up a person mentioned for another reason. The first confident Person entity is used.
- **Sessions are in memory.** They are lost on restart and are not shared across App Service
  instances, so a deployed form can break mid-conversation if the app restarts.
- **Date ambiguity:** "next Tuesday" resolves to the next occurrence after today, so it may
  not match what the user meant.

## Test audio

Test recordings in `tests/audio/` were generated with macOS `say`
(`--data-format=LEI16@16000`), so they are synthetic. They are git-ignored by the `*.wav` rule.
