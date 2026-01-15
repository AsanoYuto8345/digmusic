from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from typing import Deque, Optional


class Status(str, Enum):
    CHILL = "CHILL"
    HYPE = "HYPE"
    NEUTRAL = "NEUTRAL"


@dataclass
class RollingMean:
    size: int = 5
    _buf: Deque[float] = field(default_factory=lambda: deque(maxlen=5))

    def add(self, x: float) -> None:
        if self._buf.maxlen != self.size:
            old = list(self._buf)[-self.size:]
            self._buf = deque(old, maxlen=self.size)
        self._buf.append(float(x))

    def mean(self) -> Optional[float]:
        if not self._buf:
            return None
        return sum(self._buf) / len(self._buf)

    def is_ready(self) -> bool:
        return len(self._buf) >= self.size


@dataclass
class BaselineTracker:
    """
    ゆっくり追従するベースライン（指数移動平均EMA）
    """
    alpha: float = 0.02  # 小さいほどゆっくり（0.01〜0.05目安）
    value: Optional[float] = None

    def update(self, x: float) -> float:
        x = float(x)
        if self.value is None:
            self.value = x
        else:
            self.value = (1.0 - self.alpha) * self.value + self.alpha * x
        return self.value


@dataclass
class StateClassifier:
    """
    pNN50の「平均との差分」で状態を判定する。
    - smooth_size: pNN50の移動平均窓
    - chill_delta / hype_delta: ベースラインとの差分閾値（%ポイント）
    """
    smooth_size: int = 5
    baseline_alpha: float = 0.02

    chill_delta: float = 6.0  # baselineより +6%以上なら CHILL（調整可）
    hype_delta: float = 6.0   # baselineより -6%以上なら HYPE（調整可）

    smooth: RollingMean = field(init=False)
    baseline: BaselineTracker = field(init=False)

    def __post_init__(self) -> None:
        self.smooth = RollingMean(size=self.smooth_size)
        self.baseline = BaselineTracker(alpha=self.baseline_alpha)

    def update(self, pnn50: float) -> tuple[Optional[float], Optional[float], Status]:
        """
        戻り値:
          (smoothed_pnn50, baseline, status)
        """
        self.smooth.add(pnn50)
        sm = self.smooth.mean()
        if sm is None or not self.smooth.is_ready():
            return None, None, Status.NEUTRAL

        base = self.baseline.update(sm)
        delta = sm - base

        if delta >= self.chill_delta:
            return sm, base, Status.CHILL
        if delta <= -self.hype_delta:
            return sm, base, Status.HYPE
        return sm, base, Status.NEUTRAL
