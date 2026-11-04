"""Safe, deliberately tiny messages sent through the tmux transport."""

from __future__ import annotations

from dataclasses import dataclass


MAX_DOORBELL_LENGTH = 256


def validate_doorbell_token(token: str) -> str:
    """Return a safe literal token or reject terminal-control input."""

    if not isinstance(token, str) or not token or token != token.strip():
        raise ValueError("doorbell token must be non-empty and trimmed")
    if len(token) > MAX_DOORBELL_LENGTH:
        raise ValueError("doorbell token is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in token):
        raise ValueError("doorbell token must not contain control characters")
    return token


@dataclass(frozen=True, slots=True)
class SendResult:
    """Transport evidence, not an agent acknowledgement."""

    sent: bool
    endpoint_matched: bool
    detail: str

    @property
    def accepted(self) -> bool:
        return self.sent and self.endpoint_matched
