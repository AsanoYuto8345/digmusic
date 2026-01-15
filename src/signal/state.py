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
    移動平均（判定のブレを抑える）
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
    ・最初の安静区間から baseline_hr, baseline_pnn50 を固定
    ・HR と pNN50 の論理積で状態判定を行う

    CHILL:
        pNN50 ↑ かつ HR ↑していない

    HYPE:
        HR ↑ かつ pNN50 ↓
    """

    smooth_size: int = 5
    hr_smooth_size: int = 3
    status_switch_threshold: int = 3

    # --- CHILL条件 ---
    chill_pnn50_ratio: float = 1.05   # baselineより +5%
    chill_hr_ratio: float = 1.06      # baselineより +6%までOK

    # --- HYPE条件 ---
    hype_hr_ratio: float = 1.05       # baselineより +5%
    hype_pnn50_ratio: float = 0.95    # baselineより -5%

    smooth: RollingMean = field(init=False)
    hr_smooth: RollingMean = field(init=False)

    baseline_pnn50: Optional[float] = None
    baseline_hr: Optional[float] = None
    _current_status: Status = field(default=Status.NEUTRAL, init=False)
    _transition_target: Status = field(default=Status.NEUTRAL, init=False)
    _transition_hits: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._reset_runtime_state()

    # -------------------
    # baseline 設定
    # -------------------

    def set_baseline(self, baseline_pnn50: float, baseline_hr: float) -> None:
        self.baseline_pnn50 = float(baseline_pnn50)
        self.baseline_hr = float(baseline_hr)
        self._reset_runtime_state()

    def has_baseline(self) -> bool:
        return self.baseline_pnn50 is not None and self.baseline_hr is not None

    # -------------------
    # メイン更新
    # -------------------

    def update(
        self,
        pnn50: float,
        hr: Optional[float],
    ) -> tuple[Optional[float], Optional[float], Status]:
        """
        戻り値:
            (smoothed_pnn50, baseline_pnn50, status)

        baseline未設定 or 平滑化不足の間は NEUTRAL
        """

        self.smooth.add(pnn50)
        sm = self.smooth.mean()

        if hr is not None:
            self.hr_smooth.add(hr)
        hr_sm = self.hr_smooth.mean()

        if self.baseline_pnn50 is None or self.baseline_hr is None:
            return sm, self.baseline_pnn50, Status.NEUTRAL

        if (
            sm is None
            or not self.smooth.is_ready()
            or hr_sm is None
            or not self.hr_smooth.is_ready()
        ):
            return sm, self.baseline_pnn50, Status.NEUTRAL

        # -------------------
        # 判定ロジック
        # -------------------

        # CHILL: 揺らぎ↑ かつ 心拍が上がっていない
        candidate = Status.NEUTRAL

        if (
            sm >= self.baseline_pnn50 * self.chill_pnn50_ratio
            and hr_sm <= self.baseline_hr * self.chill_hr_ratio
        ):
            candidate = Status.CHILL
        elif (
            hr_sm >= self.baseline_hr * self.hype_hr_ratio
            and sm <= self.baseline_pnn50 * self.hype_pnn50_ratio
        ):
            candidate = Status.HYPE

        stabilized = self._stabilize_status(candidate)
        return sm, self.baseline_pnn50, stabilized

    def _stabilize_status(self, candidate: Status) -> Status:
        threshold = max(1, int(self.status_switch_threshold))

        if candidate == self._current_status:
            self._transition_hits = 0
            self._transition_target = candidate
            return self._current_status

        if candidate != self._transition_target:
            self._transition_target = candidate
            self._transition_hits = 1
            return self._current_status

        self._transition_hits += 1
        if self._transition_hits >= threshold:
            self._current_status = candidate
            self._transition_hits = 0
            self._transition_target = candidate

        return self._current_status

    def _reset_runtime_state(self) -> None:
        self.smooth = RollingMean(size=self.smooth_size)
        self.hr_smooth = RollingMean(size=self.hr_smooth_size)
        self._current_status = Status.NEUTRAL
        self._transition_target = Status.NEUTRAL
        self._transition_hits = 0
