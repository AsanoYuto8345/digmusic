# digmusic

## 概要
Arduino で取得したセンサー情報を取り込み、Python GUI アプリで表示・制御するためのプロジェクトです。

## 必要環境
- Python 3.10 以降 (推奨)
- Arduino IDE

## セットアップ
1. Python 依存関係のインストール
   ```bash
   pip install -r requirements.txt
   ```

2. Arduino 側のプログラム取り込み
   1. Arduino IDE を起動します。
   2. `arduino/ppg_rr_sender/ppg_rr_sender.ino` を開きます。
   3. 接続している Arduino を選択し、書き込み（Upload）します。

## 起動方法
Python アプリは `src/ui/main_gui.py` から起動します。

```bash
python src/ui/main_gui.py
```

## ディレクトリ構成
- `arduino/` : Arduino スケッチ
- `src/ui/` : GUI アプリケーション
