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


DEBUG_PRINT = False

from pathlib import Path

LOG_PATH = Path("logs") / "measure_debug.log"

def _dbg(msg: str) -> None:
    if not DEBUG_PRINT:
        return

    # 1) console
    try:
        print(msg, flush=True)
    except Exception:
        pass

    # 2) file (GUIでstdoutが死んでも残る)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass



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

        # RRの大ジャンプでバッファリセット採用（前回のバグ対策）
        self.calc = PNN50Calculator(window_beats=30, max_jump_ms=600)

        # ★判定を「若干厳しめ」に：deltaを上げる
        # ここを好みで調整してOK（10.0→もう少し厳しめなら12〜15）
        self.clf = FixedBaselineClassifier(
            smooth_size=5,
            chill_delta=10.0,
            hype_delta=10.0,
        )

        self._stop = False

        self.rest_end_epoch: Optional[float] = None
        self.rest_p_values: List[float] = []
        self.baseline_fixed: Optional[float] = None

        self.last_track_poll = 0.0
        self.track_text = "—"

        self.hr_points: List[Tuple[float, float]] = []

        # 15秒継続保存用の状態
        self._pending_status: Optional[Status] = None
        self._pending_since: Optional[float] = None
        self._pending_track: Optional[str] = None
        self._pending_saved: bool = False
        self._pending_required_sec: float = 15.0

        # 参考用（ログ）
        self._last_status: Status = Status.NEUTRAL

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

    def _reset_pending(self, reason: str) -> None:
        if self._pending_status is not None:
            _dbg(f"[PENDING] reset ({reason})")
        self._pending_status = None
        self._pending_since = None
        self._pending_track = None
        self._pending_saved = False

    def _update_pending_and_maybe_save(
        self,
        now_epoch: float,
        status: Status,
        value_to_save: float,
    ) -> None:
        """
        保存条件：
        - status が CHILL/HYPE
        - 同じstatusが15秒以上継続
        - その間 track_text が変わっていない
        - 1エピソードにつき1回だけ保存
        - trackが"—"なら保存しない
        """
        if status not in (Status.CHILL, Status.HYPE):
            self._reset_pending("status != CHILL/HYPE")
            return

        if self.track_text == "—":
            self._reset_pending("no track")
            return

        # pending開始 or 状態/曲が変わったらリセットして開始し直す
        if (
            self._pending_status != status
            or self._pending_track != self.track_text
            or self._pending_since is None
        ):
            self._pending_status = status
            self._pending_track = self.track_text
            self._pending_since = now_epoch
            self._pending_saved = False
            _dbg(f"[PENDING] start status={status.value} track='{self.track_text}'")
            return

        # すでに保存済みなら何もしない
        if self._pending_saved:
            return

        elapsed = now_epoch - self._pending_since
        if elapsed < self._pending_required_sec:
            # 進捗ログ欲しいならここで出してもいい（うるさいならコメントアウト）
            _dbg(f"[PENDING] running {status.value} {elapsed:.1f}/{self._pending_required_sec:.0f}s track='{self.track_text}'")
            return

        # 15秒継続達成 → 保存
        ts = datetime.now()
        can = self.db.should_save_event_cooldown(ts, self.cooldown_seconds)
        _dbg(f"[SAVE] eligible (15s sustained) cooldown_ok={can}")

        if not can:
            # cooldownで弾かれた場合は「保存済み扱いにはしない」
            # 次の継続でまた保存を試みる
            return

        # track_text を分割
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
        self._pending_saved = True
        _dbg(f"[SAVE] inserted event: {ts.isoformat(timespec='seconds')} {status.value} pNN50={value_to_save:.2f} '{artist} - {track}'")

    def run(self) -> Iterator[LiveState]:
        self.db.init_db()

        self.rest_end_epoch = time.time() + self.rest_total_sec
        self.rest_p_values = []
        self.baseline_fixed = None
        self._reset_pending("session start")
        self._last_status = Status.NEUTRAL

        _dbg(f"[MeasureSession] started (REST {self.rest_total_sec}s) port={self.serial_port or 'AUTO'} baud={self.baudrate}")

        for msg in rr_stream(
            port=self.serial_port,
            baudrate=self.baudrate,
            stop_check=self._stop_check,
        ):
            if self._stop:
                _dbg("[MeasureSession] stopped (flag detected)")
                return

            _dbg(f"[SERIAL] raw='{msg.raw}' rr_ms={msg.rr_ms}")

            self._poll_track()

            ok = self.calc.add_rr(msg.rr_ms)
            if not ok:
                _dbg("[CALC] add_rr rejected (invalid range) -> continue")
                continue

            hr = self.calc.hr_bpm()
            p = self.calc.pnn50_percent(min_diffs=10)
            self._push_hr(hr)

            hr_s = "None" if hr is None else f"{hr:.1f}"
            p_s = "None" if p is None else f"{p:.1f}"
            now = time.time()
            mode_s = "REST" if (self.rest_end_epoch is not None and now < self.rest_end_epoch) else "RUN?"
            _dbg(f"[CALC] HR={hr_s} bpm  pNN50={p_s}%  mode={mode_s} track='{self.track_text}'")

            # -----------------------
            # REST
            # -----------------------
            if self.rest_end_epoch is not None and now < self.rest_end_epoch:
                remain = int(self.rest_end_epoch - now)

                if p is not None:
                    self.rest_p_values.append(float(p))
                    _dbg(f"[REST] remain={remain}s  collected_pnn50={len(self.rest_p_values)}")

                # REST中は保存ロジックを動かさない
                self._reset_pending("REST mode")

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
                    raise RuntimeError(
                        "REST中にpNN50が取得できませんでした。"
                        "初期のRRが不安定な可能性があるので、センサを付け直す/数十秒待ってから再実行してね。"
                    )

                baseline = sum(self.rest_p_values) / len(self.rest_p_values)
                self.baseline_fixed = baseline
                self.clf.set_baseline(baseline)
                self.db.save_baseline(baseline)

                _dbg(f"[REST->RUN] baseline_fixed={baseline:.2f}%  samples={len(self.rest_p_values)}")

                self._reset_pending("baseline fixed")

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
                self._reset_pending("pNN50 None")

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
                self._reset_pending("pNN50 None (no baseline)")
                continue

            # -----------------------
            # RUN: 判定
            # -----------------------
            sm, base, status = self.clf.update(float(p))
            _dbg(f"[STATE] pNN50={p:.2f}% smoothed={None if sm is None else round(sm,2)} base={None if base is None else round(base,2)} status={status.value}")

            # ★保存に使う値は「smoothed優先、なければpNN50」
            value_for_save = float(sm) if sm is not None else float(p)

            # 15秒継続判定 → 保存
            self._update_pending_and_maybe_save(
                now_epoch=time.time(),
                status=status,
                value_to_save=value_for_save,
            )

            yield LiveState(
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

            self._last_status = status

        _dbg("[MeasureSession] rr_stream ended")
