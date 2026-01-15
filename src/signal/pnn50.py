from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Optional


@dataclass
class PNN50Calculator:
    """
    RR(ms) を順に追加していき、直近 window_beats 拍分で pNN50(%) を計算する。
    - |RR[i]-RR[i-1]| > threshold_ms の割合(%)
    - 外れ値RRは捨てる
    - 直前RRからの急変も捨てる（偽ピーク対策）
    """
    window_beats: int = 30
    threshold_ms: int = 50
    rr_min_ms: int = 300
    rr_max_ms: int = 2000

    # ★追加：急変フィルタ
    max_jump_ms: int = 250  # 直前RRとの差がこれより大きければ捨てる（調整可）

    rr: Deque[int] = field(default_factory=lambda: deque(maxlen=30))

    def add_rr(self, rr_ms: int) -> bool:
        if rr_ms < self.rr_min_ms or rr_ms > self.rr_max_ms:
            return False

        if self.rr:
            prev = self.rr[-1]
            if abs(rr_ms - prev) > self.max_jump_ms:
                return False

        if self.rr.maxlen != self.window_beats:
            old = list(self.rr)[-self.window_beats:]
            self.rr = deque(old, maxlen=self.window_beats)

        self.rr.append(rr_ms)
        return True

    def is_ready(self) -> bool:
        return len(self.rr) >= self.window_beats

    def pnn50_percent(self) -> Optional[float]:
        if not self.is_ready():
            return None

        diffs = [abs(self.rr[i] - self.rr[i - 1]) for i in range(1, len(self.rr))]
        if not diffs:
            return None

        count = sum(1 for d in diffs if d > self.threshold_ms)
        return (count / len(diffs)) * 100.0

    def hr_bpm(self) -> Optional[float]:
        if not self.rr:
            return None
        return 60000.0 / float(self.rr[-1])
