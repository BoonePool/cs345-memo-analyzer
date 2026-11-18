"""Part B — Speech-to-Text using continuous recognition.

Continuous recognition is used (not recognize_once) so that 20–40 second memos
are transcribed in full. The SDK is event-driven, so we block on a
threading.Event that is set when the recognizer stops or fails.
"""

import os
import threading

import azure.cognitiveservices.speech as speechsdk

# Languages the recognizer may auto-detect (Part I Track 1 "multilingual memos"
# can extend this list).
CANDIDATE_LANGUAGES = ["en-US", "es-ES", "fr-FR", "de-DE"]

# Hard upper bound on how long we wait for a single file to finish.
TRANSCRIPTION_TIMEOUT_SECONDS = 300

TICKS_PER_SECOND = 10_000_000  # Speech SDK offsets/durations are in 100-ns ticks


class UnsupportedAudioFormat(Exception):
    """The Speech SDK could not parse the audio container/codec (maps to HTTP 415)."""


class TranscriptionError(Exception):
    """Any other failure talking to, or inside, the Speech service (maps to HTTP 500)."""


# Substrings the SDK puts in cancellation error_details when it cannot parse audio.
_FORMAT_ERROR_MARKERS = ("0xa", "invalid_header", "invalid header", "unsupported", "format")


def _classify_error(message: str) -> Exception:
    """Map an SDK error message to the exception that decides the HTTP status."""
    if any(marker in message.lower() for marker in _FORMAT_ERROR_MARKERS):
        return UnsupportedAudioFormat(
            "Audio could not be decoded. Upload 16 kHz mono PCM WAV or MP3 "
            f"(Speech SDK said: {message})"
        )
    return TranscriptionError(message)


def _speech_config() -> speechsdk.SpeechConfig:
    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    # Detailed output includes per-word offsets and confidences in the JSON payload.
    config.output_format = speechsdk.OutputFormat.Detailed
    config.set_property(
        speechsdk.PropertyId.SpeechServiceResponse_RequestWordLevelTimestamps, "true"
    )
    return config


def _parse_words(result: speechsdk.SpeechRecognitionResult) -> list[dict]:
    """Extract per-word timing and confidence from the detailed JSON payload."""
    import json

    try:
        payload = json.loads(result.json)
        best = payload["NBest"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return []

    words = []
    base_offset = result.offset / TICKS_PER_SECOND
    for w in best.get("Words", []):
        words.append({
            "word": w.get("Word", ""),
            "offset": round(base_offset + w.get("Offset", 0) / TICKS_PER_SECOND, 3),
            "duration": round(w.get("Duration", 0) / TICKS_PER_SECOND, 3),
            "confidence": round(w.get("Confidence", 0.0), 3),
        })
    return words


def _segment_confidence(result: speechsdk.SpeechRecognitionResult) -> float | None:
    import json

    try:
        return float(json.loads(result.json)["NBest"][0]["Confidence"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def transcribe_file(path: str) -> dict:
    """Transcribe a WAV or MP3 file and return the /transcribe response body."""
    config = _speech_config()
    audio_config = speechsdk.audio.AudioConfig(filename=path)
    auto_detect = speechsdk.AutoDetectSourceLanguageConfig(
        languages=CANDIDATE_LANGUAGES
    )
    try:
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect,
        )  # the SDK opens and parses the file here
    except RuntimeError as exc:
        raise _classify_error(str(exc)) from exc

    finished = threading.Event()
    segments: list[speechsdk.SpeechRecognitionResult] = []
    detected = {"language": None}
    errors: list[str] = []

    def on_recognized(evt):
        result = evt.result
        if result.reason == speechsdk.ResultReason.RecognizedSpeech and result.text:
            segments.append(result)
            if detected["language"] is None:
                detected["language"] = speechsdk.AutoDetectSourceLanguageResult(
                    result
                ).language

    def on_canceled(evt):
        details = evt.cancellation_details
        if details.reason == speechsdk.CancellationReason.Error:
            errors.append(details.error_details or "unknown error")
        finished.set()

    def on_stopped(evt):
        finished.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_stopped)

    timed_out = False
    try:
        recognizer.start_continuous_recognition_async().get()
    except RuntimeError as exc:
        # The SDK sometimes raises here instead of emitting a canceled event,
        # e.g. for a file whose header it cannot parse (SPXERR_INVALID_HEADER).
        errors.append(str(exc))
    else:
        timed_out = not finished.wait(timeout=TRANSCRIPTION_TIMEOUT_SECONDS)
    finally:
        try:
            recognizer.stop_continuous_recognition_async().get()
        except RuntimeError:
            pass

    if errors:
        raise _classify_error(errors[0])
    if timed_out:
        raise TranscriptionError("Transcription timed out")

    words: list[dict] = []
    confidences: list[float] = []
    duration = 0.0
    for seg in segments:
        words.extend(_parse_words(seg))
        conf = _segment_confidence(seg)
        if conf is not None:
            confidences.append(conf)
        end = (seg.offset + seg.duration) / TICKS_PER_SECOND
        duration = max(duration, end)

    transcript = " ".join(seg.text for seg in segments).strip()
    overall_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

    return {
        "transcript": transcript,
        "language": detected["language"] or "en-US",
        "duration_seconds": round(duration, 2),
        "confidence": overall_confidence,
        "words": words,
    }
