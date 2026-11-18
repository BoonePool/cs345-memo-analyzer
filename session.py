"""In-memory form sessions for the Voice Form Assistant.

Sessions live in process memory, so they are lost on restart and are not shared
between App Service instances. That is acceptable for the assignment and is
documented in the README as a limitation.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field

SESSION_TTL_SECONDS = 30 * 60


@dataclass
class FieldState:
    value: str
    confidence: float | None
    source_text: str | None
    source: str                 # "speech" (filled from an utterance) or "correction"
    first_try: bool             # filled from speech and never corrected (Part G metric)


@dataclass
class FormSession:
    id: str
    fields: dict[str, FieldState] = field(default_factory=dict)
    turns: int = 0
    corrections: int = 0
    status: str = "collecting"  # collecting | confirming | submitted
    last_seen: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, FormSession] = {}
        self._lock = threading.Lock()

    def create(self) -> FormSession:
        with self._lock:
            self._purge_expired()
            session = FormSession(id=uuid.uuid4().hex)
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> FormSession | None:
        with self._lock:
            self._purge_expired()
            session = self._sessions.get(session_id)
            if session:
                session.last_seen = time.time()
            return session

    def _purge_expired(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        expired = [sid for sid, s in self._sessions.items() if s.last_seen < cutoff]
        for sid in expired:
            del self._sessions[sid]


store = SessionStore()
