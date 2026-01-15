from __future__ import annotations

from datetime import datetime

from src.sensors.serial_rr_reader import rr_stream
from src.signal.pnn50 import PNN50Calculator
from src.signal.state import StateClassifier, Status
from src.music.readmusic import get_now_playing

from src.storage.db import get_connection, init_db
from src.storage.models import Event  # source無し版のEventを想定
from src.storage.repository import insert_event, should_save_event


DB_PATH = "data/digmusic.db"


def main():
    conn = get_connection(DB_PATH)
    init_db(conn)

    calc = PNN50Calculator(window_beats=30, max_jump_ms=250)
    clf = StateClassifier(
        smooth_size=5,
        baseline_alpha=0.02,
        chill_delta=6.0,
        hype_delta=6.0,
    )

    last_status = Status.NEUTRAL

    print("Start event logger (Ctrl+C to stop)")
    for msg in rr_stream():
        if not calc.add_rr(msg.rr_ms):
            # デバッグしたければここをprintしてもOK
            continue

        p = calc.pnn50_percent()
        hr = calc.hr_bpm()
        if p is None:
            continue

        sm, base, status = clf.update(p)
        if sm is None or base is None:
            # 平滑化が溜まるまでは表示だけでもOK
            continue

        # 状態モニタ（見たいなら）
        print(f"HR={hr:5.1f}  pNN50={p:5.1f}%  sm={sm:5.1f}% base={base:5.1f}% -> {status.value}")

        # 「NEUTRAL→CHILL/HYPE に入った瞬間」だけ保存対象
        if last_status != status and status in (Status.CHILL, Status.HYPE):
            ts = datetime.now()

            now_playing = get_now_playing()
            if now_playing is None:
                # 曲が取れないなら保存しない（or Unknownで保存でも可）
                print("[WARN] Spotify track not available; skip saving.")
                last_status = status
                continue

            artist, track = now_playing

            # 連続保存防止（同曲/クールダウン）
            if should_save_event(
                conn=conn,
                ts=ts,
                status=status,         # repository側がEnum受ける想定（違うなら status.value）
                track_name=track,
                artist_name=artist,
                cooldown_seconds=60,
            ):
                ev = Event(
                    ts=ts,
                    status=status,       # models.pyがEnumならOK。strなら status.value
                    pnn50=float(sm),     # 平滑化した値を保存（おすすめ）
                    track_name=track,
                    artist_name=artist,
                )
                new_id = insert_event(conn, ev)
                print(f"[SAVED] id={new_id} {status.value} pNN50={sm:.1f}% {artist} - {track}")
            else:
                print("[SKIP] guarded by cooldown/same-track")

        last_status = status


if __name__ == "__main__":
    main()
