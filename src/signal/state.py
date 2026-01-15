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
    """
    pNN50の移動平均用（判定のブレを抑える）
    """
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
class FixedBaselineClassifier:
    """
    baselineを動的に更新せず、「最初の安静1分の平均pNN50」を固定基準として使う。
    判定は smoothed_pnn50 - baseline の差分（%ポイント）で行う。
    """
    smooth_size: int = 5
    chill_delta: float = 6.0   # baselineより +6%以上で CHILL
    hype_delta: float = 6.0    # baselineより -6%以上で HYPE

    smooth: RollingMean = field(init=False)
    baseline: Optional[float] = None

    def __post_init__(self) -> None:
        self.smooth = RollingMean(size=self.smooth_size)

    def set_baseline(self, baseline_pnn50: float) -> None:
        self.baseline = float(baseline_pnn50)

    def has_baseline(self) -> bool:
        return self.baseline is not None

    def update(self, pnn50: float) -> tuple[Optional[float], Optional[float], Status]:
        """
        戻り値:
          (smoothed_pnn50, baseline, status)
        baseline未設定 or 平滑化不足の間は NEUTRAL を返す。
        """
        self.smooth.add(pnn50)
        sm = self.smooth.mean()

        if self.baseline is None:
            return sm, None, Status.NEUTRAL

        if sm is None or not self.smooth.is_ready():
            return sm, self.baseline, Status.NEUTRAL

        delta = sm - self.baseline
        if delta >= self.chill_delta:
            return sm, self.baseline, Status.CHILL
        if delta <= -self.hype_delta:
            return sm, self.baseline, Status.HYPE
        return sm, self.baseline, Status.NEUTRAL
