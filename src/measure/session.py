from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple, Iterator

from src.music.readmusic import get_now_playing
from src.sensors.serial_rr_reader import rr_stream
from src.signal.pnn50 import PNN50Calculator
from src.signal.state import FixedBaselineClassifier, Status
from src.storage.db import DigMusicDB, EventRow


# =========================
# Debug switch
# =========================
DEBUG_PRINT = True


def _dbg(msg: str) -> None:
    if DEBUG_PRINT:
        print(msg, flush=True)


@dataclass
class LiveState:
    mode: str  # "REST" or "RUN"
    rest_remain_sec: Optional[int]
    hr: Optional[float]
    pnn50: Optional[float]
    smoothed: Optional[float]
    baseline: Optional[float]
    status: Status
    track_text: str
    hr_points: List[Tuple[float, float]]  # (epoch, hr)


class MeasureSession:
    def __init__(
        self,
        db: DigMusicDB,
        rest_total_sec: int = 60,
        hr_window_sec: float = 10.0,
        track_poll_interval: float = 2.0,
        cooldown_seconds: int = 60,
        serial_port: Optional[str] = None,
        baudrate: int = 115200,
    ):
        self.db = db
        self.rest_total_sec = int(rest_total_sec)
        self.hr_window_sec = float(hr_window_sec)
        self.track_poll_interval = float(track_poll_interval)
        self.cooldown_seconds = int(cooldown_seconds)

        self.serial_port = serial_port
        self.baudrate = baudrate

        self.calc = PNN50Calculator(window_beats=30, max_jump_ms=250)
        self.clf = FixedBaselineClassifier(smooth_size=5, chill_delta=6.0, hype_delta=6.0)

        self._stop = False

        self.rest_end_epoch: Optional[float] = None
        self.rest_p_values: List[float] = []
        self.baseline_fixed: Optional[float] = None

        self.last_track_poll = 0.0
        self.track_text = "—"

        self.hr_points: List[Tuple[float, float]] = []
        self.last_status = Status.NEUTRAL

    def stop(self) -> None:
        self._stop = True
        _dbg("[MeasureSession] stop requested")

    def _stop_check(self) -> bool:
        return self._stop

    def _poll_track(self) -> None:
        now = time.time()
        if now - self.last_track_poll < self.track_poll_interval:
            return
        self.last_track_poll = now

        np = get_now_playing()
        if np is None:
            self.track_text = "—"
            return
        artist, track = np
        self.track_text = f"{artist or 'Unknown'} - {track or 'Unknown'}"

    def _push_hr(self, hr: Optional[float]) -> None:
        if hr is None:
            return
        now = time.time()
        self.hr_points.append((now, float(hr)))
        start = now - self.hr_window_sec
        self.hr_points = [(t, v) for (t, v) in self.hr_points if t >= start]

    def run(self) -> Iterator[LiveState]:
        self.db.init_db()

        self.rest_end_epoch = time.time() + self.rest_total_sec
        self.rest_p_values = []
        self.baseline_fixed = None
        self.last_status = Status.NEUTRAL

        _dbg(f"[MeasureSession] started (REST {self.rest_total_sec}s) port={self.serial_port or 'AUTO'} baud={self.baudrate}")

        for msg in rr_stream(
            port=self.serial_port,
            baudrate=self.baudrate,
            stop_check=self._stop_check,
        ):
            if self._stop:
                _dbg("[MeasureSession] stopped (flag detected)")
                return

            # 受信RR
            _dbg(f"[SERIAL] raw='{msg.raw}' rr_ms={msg.rr_ms}")

            # 曲情報（低頻度ポーリング）
            self._poll_track()

            ok = self.calc.add_rr(msg.rr_ms)
            if not ok:
                _dbg("[CALC] add_rr rejected (maybe outlier/invalid) -> continue")
                continue

            hr = self.calc.hr_bpm()
            p = self.calc.pnn50_percent()
            self._push_hr(hr)

            # 計算結果（pNN50がまだ None のときも出す）
            if hr is None:
                hr_s = "None"
            else:
                hr_s = f"{hr:.1f}"
            if p is None:
                p_s = "None"
            else:
                p_s = f"{p:.1f}"

            _dbg(f"[CALC] HR={hr_s} bpm  pNN50={p_s}%  mode={'REST' if (self.rest_end_epoch is not None and time.time() < self.rest_end_epoch) else 'RUN?'} track='{self.track_text}'")

            now = time.time()

            # -----------------------
            # REST
            # -----------------------
            if self.rest_end_epoch is not None and now < self.rest_end_epoch:
                remain = int(self.rest_end_epoch - now)
                if p is not None:
                    self.rest_p_values.append(float(p))
                    _dbg(f"[REST] remain={remain}s  collected_pnn50={len(self.rest_p_values)}")

                yield LiveState(
                    mode="REST",
                    rest_remain_sec=remain,
                    hr=hr,
                    pnn50=(float(p) if p is not None else None),
                    smoothed=None,
                    baseline=None,
                    status=Status.NEUTRAL,
                    track_text=self.track_text,
                    hr_points=list(self.hr_points),
                )
                continue

            # -----------------------
            # REST終了 → baseline確定
            # -----------------------
            if self.rest_end_epoch is not None and now >= self.rest_end_epoch:
                self.rest_end_epoch = None

                if len(self.rest_p_values) == 0:
                    _dbg("[REST] baseline failed: no pNN50 samples")
                    raise RuntimeError("REST中にpNN50が取得できませんでした。センサを確認してね。")

                baseline = sum(self.rest_p_values) / len(self.rest_p_values)
                self.baseline_fixed = baseline
                self.clf.set_baseline(baseline)
                self.db.save_baseline(baseline)

                _dbg(f"[REST->RUN] baseline_fixed={baseline:.2f}%  samples={len(self.rest_p_values)}")

                # baseline確定をUIへ通知（pNN50がNoneでもOK）
                yield LiveState(
                    mode="RUN",
                    rest_remain_sec=None,
                    hr=hr,
                    pnn50=(float(p) if p is not None else None),
                    smoothed=None,
                    baseline=float(baseline),
                    status=Status.NEUTRAL,
                    track_text=self.track_text,
                    hr_points=list(self.hr_points),
                )
                continue

            # -----------------------
            # RUN: baseline確定後、pNN50がまだ None でも UI 更新を返す
            # -----------------------
            if self.baseline_fixed is not None and p is None:
                _dbg("[RUN] baseline fixed but pNN50 is None (warming up) -> yield RUN/NEUTRAL")
                yield LiveState(
                    mode="RUN",
                    rest_remain_sec=None,
                    hr=hr,
                    pnn50=None,
                    smoothed=None,
                    baseline=float(self.baseline_fixed),
                    status=Status.NEUTRAL,
                    track_text=self.track_text,
                    hr_points=list(self.hr_points),
                )
                continue

            if p is None:
                _dbg("[RUN] pNN50 is None and baseline not fixed? -> skip")
                continue

            # -----------------------
            # RUN: 判定
            # -----------------------
            sm, base, status = self.clf.update(float(p))
            _dbg(f"[STATE] pNN50={p:.2f}% smoothed={None if sm is None else round(sm,2)} base={None if base is None else round(base,2)} status={status.value}")

            state = LiveState(
                mode="RUN",
                rest_remain_sec=None,
                hr=hr,
                pnn50=float(p),
                smoothed=sm,
                baseline=base,
                status=status,
                track_text=self.track_text,
                hr_points=list(self.hr_points),
            )
            yield state

            # -----------------------
            # イベント保存
            # -----------------------
            if self.last_status != status and status in (Status.CHILL, Status.HYPE):
                ts = datetime.now()

                if self.track_text == "—":
                    _dbg("[SAVE] skipped (no track)")
                else:
                    can = self.db.should_save_event_cooldown(ts, self.cooldown_seconds)
                    _dbg(f"[SAVE] status change {self.last_status.value}->{status.value} cooldown_ok={can}")
                    if can:
                        value_to_save = float(sm) if sm is not None else float(p)
                        if " - " in self.track_text:
                            artist, track = self.track_text.split(" - ", 1)
                        else:
                            artist, track = "Unknown", self.track_text

                        self.db.insert_event(EventRow(
                            ts=ts,
                            status=status,
                            pnn50=value_to_save,
                            artist_name=artist,
                            track_name=track,
                        ))
                        _dbg(f"[SAVE] inserted event: {ts.isoformat(timespec='seconds')} {status.value} pNN50={value_to_save:.2f} '{artist} - {track}'")

            self.last_status = status

        _dbg("[MeasureSession] rr_stream ended")
