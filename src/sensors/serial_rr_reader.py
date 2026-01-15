from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional, Callable
import time

import serial
import serial.tools.list_ports


@dataclass(frozen=True)
class RRMessage:
    rr_ms: int
    raw: str


def _auto_detect_port() -> Optional[str]:
    """
    Arduinoっぽいポートを雑に探す。見つからなければ None。
    """
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None
    # まずは "Arduino" っぽいの優先
    for p in ports:
        desc = (p.description or "").lower()
        manu = (p.manufacturer or "").lower()
        if "arduino" in desc or "arduino" in manu:
            return p.device
    # それ以外は先頭
    return ports[0].device


def rr_stream(
    port: Optional[str] = None,
    baudrate: int = 115200,
    stop_check: Optional[Callable[[], bool]] = None,
) -> Iterator[RRMessage]:
    """
    Arduinoから "RR,993" みたいな1行を受け取る想定。

    stop_check が True を返したら終了する。
    重要：timeout付き読み取りにして、ブロックで固まらないようにする。
    """
    if port is None:
        port = _auto_detect_port()
        if port is None:
            raise RuntimeError("シリアルポートが見つかりませんでした。COM番号を指定してください。")

    # timeoutが肝：ここが無いと stop しても抜けられず固まる
    ser = serial.Serial(port, baudrate=baudrate, timeout=1)

    try:
        while True:
            if stop_check is not None and stop_check():
                return

            line = ser.readline()  # timeout=1 なので最大1秒で返る
            if not line:
                continue

            try:
                s = line.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue

            # 例: "RR,993"
            if not s.startswith("RR,"):
                continue

            parts = s.split(",", 1)
            if len(parts) != 2:
                continue

            try:
                rr = int(parts[1])
            except ValueError:
                continue

            yield RRMessage(rr_ms=rr, raw=s)

    finally:
        try:
            ser.close()
        except Exception:
            pass
