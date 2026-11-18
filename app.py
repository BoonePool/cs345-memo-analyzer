# app.py — entry point (Azure App Service looks for this filename).
# load_dotenv() runs first so the Azure SDK clients see the environment variables.
from dotenv import load_dotenv

load_dotenv()

import os
import tempfile

from flask import Flask, jsonify, request

from language_service import analyze_text
from speech_service import TranscriptionError, UnsupportedAudioFormat, transcribe_file

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB, per Part B2
ALLOWED_EXTENSIONS = {".wav", ".mp3"}
TEMP_DIR = "temp_audio"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="File too large; maximum upload size is 25 MB"), 413


@app.route("/transcribe", methods=["POST"])
def transcribe():
    upload = request.files.get("audio")
    if upload is None or upload.filename == "":
        return jsonify(error="Send a multipart upload with a field named 'audio'"), 400

    extension = os.path.splitext(upload.filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify(
            error=f"Unsupported file type '{extension}'. Upload a .wav or .mp3 file"
        ), 415

    os.makedirs(TEMP_DIR, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=TEMP_DIR, suffix=extension)
    try:
        with os.fdopen(fd, "wb") as handle:
            upload.save(handle)
        result = transcribe_file(temp_path)
    except UnsupportedAudioFormat as exc:
        return jsonify(error=str(exc)), 415
    except TranscriptionError as exc:
        return jsonify(error=f"Speech service error: {exc}"), 500
    finally:
        # Always delete the temporary audio, even on failure.
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return jsonify(result), 200


@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify(error="JSON body must include a non-empty 'text' field"), 400

    try:
        return jsonify(analyze_text(text)), 200
    except Exception as exc:  # surface Language service failures as a 502
        return jsonify(error=f"Language service error: {exc}"), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
