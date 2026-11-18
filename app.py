# app.py — entry point (Azure App Service looks for this filename).
# load_dotenv() runs first so the Azure SDK clients see the environment variables.
from dotenv import load_dotenv

load_dotenv()

import os
import tempfile
from datetime import date

from flask import Flask, jsonify, request

from form_schema import FIELD_ORDER, FIELDS, REQUEST_TYPE_LABELS, REQUEST_TYPES
from language_service import extract_fields
from session import FieldState, FormSession, store
from speech_service import TranscriptionError, UnsupportedAudioFormat, transcribe_file

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, per Part B2
ALLOWED_EXTENSIONS = {".wav", ".mp3"}
TEMP_DIR = "temp_audio"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="File too large; maximum upload size is 25 MB"), 413


class BadUpload(Exception):
    """Client error in the uploaded audio (maps to 400 or 415)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _transcribe_upload(upload) -> dict:
    """Save an uploaded file to temp_audio/, transcribe it, and always delete the file."""
    extension = os.path.splitext(upload.filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise BadUpload(
            f"Unsupported file type '{extension}'. Upload a .wav or .mp3 file", 415
        )

    os.makedirs(TEMP_DIR, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=TEMP_DIR, suffix=extension)
    try:
        with os.fdopen(fd, "wb") as handle:
            upload.save(handle)
        return transcribe_file(temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ---------------------------------------------------------------- Part B

@app.route("/transcribe", methods=["POST"])
def transcribe():
    upload = request.files.get("audio")
    if upload is None or upload.filename == "":
        return jsonify(error="Send a multipart upload with a field named 'audio'"), 400
    try:
        return jsonify(_transcribe_upload(upload)), 200
    except BadUpload as exc:
        return jsonify(error=str(exc)), exc.status
    except UnsupportedAudioFormat as exc:
        return jsonify(error=str(exc)), 415
    except TranscriptionError as exc:
        return jsonify(error=f"Speech service error: {exc}"), 500


# ------------------------------------------------- Voice Form Assistant

def _display(field_name: str, value: str) -> str:
    if field_name == "date":
        return date.fromisoformat(value).strftime("%A, %B %d, %Y").replace(" 0", " ")
    if field_name == "request_type":
        return REQUEST_TYPE_LABELS.get(value, value)
    return value


def _state(session: FormSession) -> dict:
    """Build the response body the frontend renders and reads aloud."""
    fields = {}
    missing = []
    for name in FIELD_ORDER:
        state = session.fields.get(name)
        if state is None:
            fields[name] = None
            missing.append(name)
        else:
            fields[name] = {
                "label": FIELDS[name]["label"],
                "value": state.value,
                "display": _display(name, state.value),
                "source": state.source,
                "first_try": state.first_try,
            }

    if missing:
        next_question = FIELDS[missing[0]]["question"]
        confirmation = None
    else:
        next_question = None
        parts = [
            f"your name is {session.fields['name'].value}",
            f"the date is {_display('date', session.fields['date'].value)}",
            f"the request is a {_display('request_type', session.fields['request_type'].value)}",
        ]
        confirmation = "Let me confirm: " + ", ".join(parts[:-1]) + ", and " + parts[-1] + ". Is that correct?"

    return {
        "session_id": session.id,
        "status": session.status,
        "turns": session.turns,
        "corrections": session.corrections,
        "fields": fields,
        "missing": missing,
        "next_question": next_question,
        "confirmation_text": confirmation,
    }


def _apply_candidates(session: FormSession, candidates: dict) -> None:
    for name in FIELD_ORDER:
        if name in candidates and name not in session.fields:
            c = candidates[name]
            session.fields[name] = FieldState(
                value=c["value"],
                confidence=c["confidence"],
                source_text=c["source_text"],
                source="speech",
                first_try=True,
            )
    session.status = "confirming" if len(session.fields) == len(FIELD_ORDER) else "collecting"


@app.route("/form/start", methods=["POST"])
def form_start():
    session = store.create()
    return jsonify(_state(session)), 201


@app.route("/form/turn", methods=["POST"])
def form_turn():
    """One spoken (or typed) answer. Accepts multipart 'audio' or JSON {'text'}."""
    session_id = request.values.get("session_id") or (request.get_json(silent=True) or {}).get("session_id")
    session = store.get(session_id) if session_id else store.create()
    if session is None:
        return jsonify(error="Unknown session_id; call POST /form/start"), 404
    if session.status == "submitted":
        return jsonify(error="This form was already submitted"), 409

    upload = request.files.get("audio")
    body = request.get_json(silent=True) or {}
    if upload is not None and upload.filename:
        try:
            transcript = _transcribe_upload(upload)["transcript"]
        except BadUpload as exc:
            return jsonify(error=str(exc)), exc.status
        except UnsupportedAudioFormat as exc:
            return jsonify(error=str(exc)), 415
        except TranscriptionError as exc:
            return jsonify(error=f"Speech service error: {exc}"), 500
    else:
        transcript = (body.get("text") or "").strip()
        if not transcript:
            return jsonify(error="Send an 'audio' upload or a JSON 'text' field"), 400

    try:
        candidates = extract_fields(transcript)
    except Exception as exc:
        return jsonify(error=f"Language service error: {exc}"), 502

    session.turns += 1
    _apply_candidates(session, candidates)
    body_out = _state(session)
    body_out["transcript"] = transcript
    body_out["heard"] = sorted(candidates)
    return jsonify(body_out), 200


@app.route("/form/correct", methods=["POST"])
def form_correct():
    """Manual correction of one field (tap-to-edit fallback). Counts against first-try accuracy."""
    body = request.get_json(silent=True) or {}
    session = store.get(body.get("session_id", ""))
    if session is None:
        return jsonify(error="Unknown session_id"), 404
    if session.status == "submitted":
        return jsonify(error="This form was already submitted"), 409

    name = body.get("field")
    value = (body.get("value") or "").strip()
    if name not in FIELDS:
        return jsonify(error=f"field must be one of {FIELD_ORDER}"), 400
    if not value:
        return jsonify(error="value is required"), 400
    if name == "request_type" and value not in REQUEST_TYPES:
        return jsonify(error=f"request_type must be one of {list(REQUEST_TYPES)}"), 400
    if name == "date":
        try:
            value = date.fromisoformat(value).isoformat()
        except ValueError:
            return jsonify(error="date must be YYYY-MM-DD"), 400

    previous = session.fields.get(name)
    if previous and previous.value != value:
        session.corrections += 1
    session.fields[name] = FieldState(
        value=value, confidence=1.0, source_text=None, source="correction", first_try=False
    )
    session.status = "confirming" if len(session.fields) == len(FIELD_ORDER) else "collecting"
    return jsonify(_state(session)), 200


@app.route("/form/confirm", methods=["POST"])
def form_confirm():
    """The user has heard the confirmation and says it is correct."""
    body = request.get_json(silent=True) or {}
    session = store.get(body.get("session_id", ""))
    if session is None:
        return jsonify(error="Unknown session_id"), 404
    if len(session.fields) < len(FIELD_ORDER):
        return jsonify(error="Form is not complete yet", missing=_state(session)["missing"]), 409
    session.status = "submitted"
    return jsonify(_state(session)), 200


@app.route("/form/<session_id>", methods=["GET"])
def form_get(session_id: str):
    session = store.get(session_id)
    if session is None:
        return jsonify(error="Unknown session_id"), 404
    return jsonify(_state(session)), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
