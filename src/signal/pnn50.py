from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Optional


@dataclass
class PNN50Calculator:
    """
    RR(ms) を順に追加していき、直近 window_beats 拍分で pNN50(%) を計算する。
    - RR差分 |RR[i]-RR[i-1]| > 50ms の割合(%)
    - 外れ値RRは捨てる
    """
    window_beats: int = 30              # 直近30拍で計算（おすすめ）
    threshold_ms: int = 50              # pNN50の定義
    rr_min_ms: int = 300                # 200bpm相当
    rr_max_ms: int = 2000               # 30bpm相当

    rr: Deque[int] = field(default_factory=lambda: deque(maxlen=30))

    def add_rr(self, rr_ms: int) -> bool:
        """RRを追加。追加できたらTrue、外れ値ならFalse。"""
        if rr_ms < self.rr_min_ms or rr_ms > self.rr_max_ms:
            return False
        # dequeのmaxlenはdataclass初期化時に固定されるので、window変更に対応したいなら再構築する
        if self.rr.maxlen != self.window_beats:
            old = list(self.rr)[-self.window_beats:]
            self.rr = deque(old, maxlen=self.window_beats)
        self.rr.append(rr_ms)
        return True

    def is_ready(self) -> bool:
        return len(self.rr) >= self.window_beats

    def pnn50_percent(self) -> Optional[float]:
        """pNN50(%)。データ不足ならNone。"""
        if len(self.rr) < 2:
            return None
        # window未満でも計算したいならここを is_ready にしない
        if not self.is_ready():
            return None

        diffs = [abs(self.rr[i] - self.rr[i - 1]) for i in range(1, len(self.rr))]
        if not diffs:
            return None

        count = sum(1 for d in diffs if d > self.threshold_ms)
        return (count / len(diffs)) * 100.0

    def hr_bpm(self) -> Optional[float]:
        """直近RRから心拍数(bpm)推定。"""
        if not self.rr:
            return None
        return 60000.0 / float(self.rr[-1])
