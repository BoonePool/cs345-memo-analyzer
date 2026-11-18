"""The Voice Form Assistant's form: what it asks for, in what order, and the allowed values.

Each field has a question the app reads aloud (Part D) and a label for the UI (Part E).
"""

FIELDS = {
    "name": {
        "label": "Name",
        "question": "What is your name?",
    },
    "date": {
        "label": "Date",
        "question": "What date is this request for?",
    },
    "request_type": {
        "label": "Request type",
        "question": "What is your request? For example, a password reset, a billing question, or technical support.",
    },
}

# Field order is the order the app asks in.
FIELD_ORDER = list(FIELDS)

# Fixed vocabulary for request_type. Keywords are matched case-insensitively
# against the transcript; the first category with a hit wins.
REQUEST_TYPES = {
    "password_reset": ["password", "reset", "locked out", "can't log in", "cannot log in", "log in"],
    "billing": ["bill", "billing", "invoice", "charge", "refund", "payment"],
    "technical_support": ["broken", "not working", "error", "crash", "won't open", "doesn't work"],
}

REQUEST_TYPE_LABELS = {
    "password_reset": "password reset",
    "billing": "billing question",
    "technical_support": "technical support",
}
