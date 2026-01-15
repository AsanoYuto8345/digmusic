from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class Status(str, Enum):
    CHILL = "CHILL"
    HYPE = "HYPE"
    NEUTRAL = "NEUTRAL"

@dataclass(frozen=True)
class Event:
    ts: datetime
    status: Status
    pnn50: float
    track_name: str
    artist_name: str
