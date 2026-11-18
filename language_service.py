"""Part C — Language analysis with Azure AI Language.

Calls key phrase extraction, named entity recognition, sentiment analysis and
(optionally) linked entities, and returns them in one structured object.
"""

import os

from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError


def _client() -> TextAnalyticsClient:
    return TextAnalyticsClient(
        endpoint=os.environ["AZURE_LANGUAGE_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["AZURE_LANGUAGE_KEY"]),
    )


def _raise_if_error(doc, operation: str) -> None:
    if doc.is_error:
        raise RuntimeError(f"{operation} failed: {doc.error.code} {doc.error.message}")


def analyze_text(text: str) -> dict:
    """Run the Language analyses on one transcript and return the /analyze body."""
    client = _client()

    phrases_doc = client.extract_key_phrases([text])[0]
    _raise_if_error(phrases_doc, "key phrase extraction")

    entities_doc = client.recognize_entities([text])[0]
    _raise_if_error(entities_doc, "entity recognition")

    sentiment_doc = client.analyze_sentiment([text])[0]
    _raise_if_error(sentiment_doc, "sentiment analysis")

    entities = [
        {
            "text": e.text,
            "category": e.category,
            "subcategory": e.subcategory,
            "confidence_score": round(e.confidence_score, 3),
        }
        for e in entities_doc.entities
    ]

    # Entity Linking is retired for new customers (see the assignment, Part C).
    # If the resource rejects the call, record that instead of failing the request.
    try:
        linked_doc = client.recognize_linked_entities([text])[0]
        _raise_if_error(linked_doc, "entity linking")
        linked = [
            {
                "name": le.name,
                "url": le.url,
                "data_source": le.data_source,
                "matches": [m.text for m in le.matches],
            }
            for le in linked_doc.entities
        ]
        linked_status = {"available": True, "entities": linked}
    except (HttpResponseError, RuntimeError) as exc:
        linked_status = {"available": False, "reason": str(exc)}

    scores = sentiment_doc.confidence_scores
    return {
        "key_phrases": list(phrases_doc.key_phrases),
        "entities": entities,
        "sentiment": {
            "label": sentiment_doc.sentiment,
            "confidence_scores": {
                "positive": round(scores.positive, 3),
                "neutral": round(scores.neutral, 3),
                "negative": round(scores.negative, 3),
            },
        },
        "linked_entities": linked_status,
    }
