from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserSession:
    user_id: int
    language: str = "pt"
    step: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0

    def expired(self) -> bool:
        return bool(self.expires_at and self.expires_at < time.time())


class SessionManager:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[int, UserSession] = {}

    def get(self, user_id: int, language: str = "pt") -> UserSession:
        session = self._sessions.get(user_id)
        if not session or session.expired():
            session = UserSession(user_id=user_id, language=language)
            self._sessions[user_id] = session
        session.language = language
        return session

    def set_step(self, user_id: int, step: str, payload: dict[str, Any], language: str = "pt") -> UserSession:
        session = UserSession(
            user_id=user_id,
            language=language,
            step=step,
            payload=payload,
            expires_at=time.time() + self.ttl_seconds,
        )
        self._sessions[user_id] = session
        return session

    def clear(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)

    def cleanup(self) -> int:
        expired = [user_id for user_id, session in self._sessions.items() if session.expired()]
        for user_id in expired:
            self._sessions.pop(user_id, None)
        return len(expired)


class RateLimiter:
    def __init__(self, window_seconds: int, max_events: int) -> None:
        self.window_seconds = window_seconds
        self.max_events = max_events
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.time()
        events = self._events[user_id]
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if not events:
            self._events.pop(user_id, None)
            events = self._events[user_id]
        if len(events) >= self.max_events:
            return False
        events.append(now)
        return True
