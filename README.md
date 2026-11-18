# Voice-Powered Memo Analyzer (CS 345 / CSC 645, Fall 2026)

A Flask service that transcribes a recorded memo with Azure AI Speech, analyses
the transcript with Azure AI Language, and (in later parts) speaks a summary back
with neural TTS and reports telemetry to Application Insights.

## Status

| Part | Description | State |
|------|-------------|-------|
| A | Azure provisioning (Speech, Language, Log Analytics, App Insights) | Done — `provision_part_a.sh` |
| B | `POST /transcribe` — continuous recognition, word-level confidence, HTTP 415 on bad audio | Done — `speech_service.py` |
| C | `POST /analyze` — key phrases, NER, sentiment, linked entities | Done — `language_service.py` |
| D–G | Summary + TTS, frontend, App Service deployment, telemetry | Not started |

## Architecture (so far)

```
client ──multipart WAV/MP3──▶ POST /transcribe ──▶ Azure AI Speech (continuous recognition, Detailed output)
                                 │                       │
                                 │                 transcript, language, duration, confidence, words[]
                                 ▼
client ──JSON {text}────────▶ POST /analyze ──▶ Azure AI Language (key phrases, NER, sentiment, linked entities)
```

- `app.py` — Flask entry point and routes. Loads `.env` before importing the SDKs.
- `speech_service.py` — `transcribe_file()`: blocks on a `threading.Event` while the
  recognizer runs, collects final segments, parses per-word timings from the detailed JSON.
- `language_service.py` — `analyze_text()`: one object with four analyses. Linked entities
  are reported as `available: false` instead of failing the request if the resource rejects them.
- Uploaded audio is written to `temp_audio/` and deleted in a `finally` block.

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

## Example calls

```bash
# Part B — transcription
curl -X POST -F "audio=@tests/audio/memo_budget.wav" http://localhost:5050/transcribe

# Part C — language analysis
curl -X POST -H "Content-Type: application/json" \
  -d '{"text":"Meeting starts at 3pm. Please review the budget proposal."}' \
  http://localhost:5050/analyze
```

Error responses: `400` missing file or text, `413` file over 25 MB, `415` unsupported
extension or audio the Speech SDK cannot decode, `500` Speech service error, `502` Language service error.

## Test audio

The test memos in `tests/audio/` were generated with macOS `say`
(`--data-format=LEI16@16000`), so they are synthetic. They are git-ignored by the `*.wav` rule.
