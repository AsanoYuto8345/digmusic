from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Iterator

import serial
from serial.tools import list_ports


@dataclass(frozen=True)
class RRMessage:
    rr_ms: int
    raw_line: str


def guess_port() -> Optional[str]:
    """
    WindowsでArduinoっぽいポートを雑に推測する。
    見つからなければ None。
    """
    ports = list(list_ports.comports())
    if not ports:
        return None

    # よくある説明文キーワード
    keywords = ["Arduino", "CH340", "USB-SERIAL", "Silicon Labs", "CP210", "FTDI"]

    for p in ports:
        desc = (p.description or "")
        if any(k.lower() in desc.lower() for k in keywords):
            return p.device

    # それっぽいのが無ければ先頭を返す
    return ports[0].device


def parse_rr_line(line: str) -> Optional[int]:
    """
    期待フォーマット:
      RR,812
    もしくは
      812
    """
    s = line.strip()
    if not s:
        return None

    if s.startswith("RR,"):
        try:
            return int(s.split(",", 1)[1])
        except Exception:
            return None

    # フォールバック: 数字だけの行
    if s.isdigit():
        return int(s)

    return None


def rr_stream(
    port: Optional[str] = None,
    baudrate: int = 115200,
    timeout: float = 1.0,
    reconnect: bool = True,
) -> Iterator[RRMessage]:
    """
    RR(ms) を延々と yield するジェネレータ。
    - Arduinoリセット直後の "READY" みたいな行は無視する
    - 切断されたら再接続する（reconnect=Trueのとき）
    """
    if port is None:
        port = guess_port()

    if port is None:
        raise RuntimeError("シリアルポートが見つかりません。Arduino接続を確認してね。")

    while True:
        try:
            with serial.Serial(port, baudrate=baudrate, timeout=timeout) as ser:
                # Arduino接続直後はリセットでゴミが来ることがあるので少し待つ
                time.sleep(1.0)
                ser.reset_input_buffer()

                while True:
                    raw = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not raw:
                        continue

                    rr = parse_rr_line(raw)
                    if rr is None:
                        # READY とかデバッグ出力とか
                        continue

                    yield RRMessage(rr_ms=rr, raw_line=raw)

        except serial.SerialException as e:
            if not reconnect:
                raise
            print(f"[WARN] serial error: {e}  -> reconnecting...")
            time.sleep(1.0)
            continue


def main():
    print("Listening RR... (Ctrl+C to stop)")
    for msg in rr_stream():
        print(f"RR(ms)={msg.rr_ms}  raw='{msg.raw_line}'")


if __name__ == "__main__":
    main()
