"""Part C (form version) — extract form fields from a transcript.

Replaces the memo analysis (key phrases, sentiment, linked entities). Each form
field is filled from a different source:

- name:         prebuilt Person entities from Azure AI Language (NER)
- date:         prebuilt DateTime entities, normalized in code to an ISO date
                (Language returns "next Tuesday" as text; it does not resolve it)
- request_type: keyword rules over FIELDS vocabulary (placeholder for a custom
                classifier or a Foundry model; see README limitations)

Each extractor returns a candidate {"value", "confidence", "source_text"} or None.
"""

import os
import re
from datetime import date, timedelta

from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from dateutil import parser as date_parser
from dateutil.parser import ParserError

from form_schema import REQUEST_TYPES

MIN_NER_CONFIDENCE = 0.6

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _client() -> TextAnalyticsClient:
    return TextAnalyticsClient(
        endpoint=os.environ["AZURE_LANGUAGE_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["AZURE_LANGUAGE_KEY"]),
    )


def normalize_date(text: str, today: date) -> str | None:
    """Turn a spoken date into YYYY-MM-DD, resolving relative phrases against today."""
    phrase = text.strip().lower()
    if phrase == "today":
        return today.isoformat()
    if phrase == "tomorrow":
        return (today + timedelta(days=1)).isoformat()

    # "tuesday" and "next tuesday" both resolve to the next occurrence strictly after today.
    match = re.search(r"\b(?:next\s+)?(" + "|".join(_WEEKDAYS) + r")\b", phrase)
    if match:
        target = _WEEKDAYS.index(match.group(1))
        days_ahead = (target - today.weekday()) % 7 or 7
        return (today + timedelta(days=days_ahead)).isoformat()

    try:
        parsed = date_parser.parse(phrase, fuzzy=True, default=_as_datetime(today)).date()
    except (ParserError, ValueError, OverflowError):
        return None

    # With no year spoken, "March 3" said in November means next March, not last March.
    if parsed < today and not re.search(r"\b\d{4}\b", phrase):
        try:
            parsed = parsed.replace(year=parsed.year + 1)
        except ValueError:  # Feb 29 in a non-leap year
            return None
    return parsed.isoformat()


def _as_datetime(d: date):
    from datetime import datetime

    return datetime(d.year, d.month, d.day)


def extract_name(entities) -> dict | None:
    people = [
        e for e in entities
        if e.category == "Person" and e.confidence_score >= MIN_NER_CONFIDENCE
    ]
    if not people:
        return None
    best = max(people, key=lambda e: e.confidence_score)
    return {
        "value": best.text,
        "confidence": round(best.confidence_score, 3),
        "source_text": best.text,
    }


def extract_date(entities, transcript: str, today: date) -> dict | None:
    for e in entities:
        if e.category != "DateTime" or e.confidence_score < MIN_NER_CONFIDENCE:
            continue
        iso = normalize_date(e.text, today)
        if iso:
            return {
                "value": iso,
                "confidence": round(e.confidence_score, 3),
                "source_text": e.text,
            }
    return None


def extract_request_type(transcript: str) -> dict | None:
    lowered = transcript.lower()
    for category, keywords in REQUEST_TYPES.items():
        for keyword in keywords:
            if keyword in lowered:
                # Keyword rules have no score; report a fixed, modest confidence.
                return {"value": category, "confidence": 0.7, "source_text": keyword}
    return None


def extract_fields(transcript: str, today: date | None = None) -> dict:
    """Return candidate values for every form field found in the transcript."""
    today = today or date.today()
    response = _client().recognize_entities([transcript])[0]
    if response.is_error:
        raise RuntimeError(f"entity recognition failed: {response.error.message}")

    entities = response.entities
    candidates = {
        "name": extract_name(entities),
        "date": extract_date(entities, transcript, today),
        "request_type": extract_request_type(transcript),
    }
    return {field: c for field, c in candidates.items() if c}
