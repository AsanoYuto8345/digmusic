from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RRStats:
    hr_bpm: Optional[float]
    pnn50: Optional[float]


class PNN50Calculator:
    """
    RR(ms)列から
      - HR(bpm)
      - pNN50(%)
    を計算する。

    重要：
    - max_jump_ms を超える大ジャンプが来たら reject せず「リセットして採用」する
      → 最初のゴミ値で永遠にrejectになる事故を防ぐ
    """

    def __init__(self, window_beats: int = 30, max_jump_ms: int = 250):
        self.window_beats = int(window_beats)
        self.max_jump_ms = int(max_jump_ms)
        self._rr: List[int] = []
        self._last_pnn50: Optional[float] = None

    def reset(self) -> None:
        self._rr.clear()
        self._last_pnn50 = None

    def add_rr(self, rr_ms: int) -> bool:
        rr_ms = int(rr_ms)

        # ざっくり妥当レンジ（明らかに壊れた値は捨てる）
        # 200ms=300bpm, 2000ms=30bpm
        if rr_ms < 200 or rr_ms > 2000:
            return False

        if len(self._rr) == 0:
            self._rr.append(rr_ms)
            return True

        prev = self._rr[-1]
        jump = abs(rr_ms - prev)

        # ★ここが今回の本命修正：
        # 大ジャンプは reject ではなく「バッファリセットして採用」
        if jump > self.max_jump_ms:
            self._rr = [rr_ms]
            return True

        # 通常追加
        self._rr.append(rr_ms)
        if len(self._rr) > self.window_beats:
            self._rr = self._rr[-self.window_beats :]
        return True

    def hr_bpm(self) -> Optional[float]:
        if not self._rr:
            return None
        rr = self._rr[-1]
        if rr <= 0:
            return None
        return 60000.0 / rr

    def pnn50_percent(self, min_diffs: int = 10) -> Optional[float]:
        """
        RR差分が min_diffs 個以上ないと None を返す。
        pNN50は「連続RR差の絶対値が50msを超えた割合(%)」
        """
        if len(self._rr) < 2:
            return None

        diffs = [abs(self._rr[i] - self._rr[i - 1]) for i in range(1, len(self._rr))]
        if len(diffs) < int(min_diffs):
            return self._last_pnn50

        cnt = sum(1 for d in diffs if d > 50)
        value = max(0.0, min(100.0, 100.0 * cnt / len(diffs)))
        self._last_pnn50 = value
        return value
