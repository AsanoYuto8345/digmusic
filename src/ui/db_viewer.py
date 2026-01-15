import sys
import csv
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QFileDialog,
    QMessageBox,
    QHeaderView,
)

# DBパス（必要ならここを変更）
DEFAULT_DB_PATH = Path("data") / "digmusic.db"


class DbViewer(QWidget):
    def __init__(self, db_path: Path):
        super().__init__()
        self.setWindowTitle("DigMusic DB Viewer")
        self.resize(1100, 650)

        self.db_path = db_path
        self.conn = None

        # --- UI 部品 ---
        self.status_combo = QComboBox()
        self.status_combo.addItems(["ALL", "CHILL", "HYPE", "NEUTRAL"])

        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("曲名 or アーティストで検索（部分一致）")

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 5000)
        self.limit_spin.setValue(200)

        self.reload_btn = QPushButton("更新")
        self.export_btn = QPushButton("CSV出力")
        self.open_btn = QPushButton("DBを選択...")

        self.table = QTableView()
        self.model = QStandardItemModel(0, 0)
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # --- レイアウト ---
        root = QVBoxLayout()

        top = QHBoxLayout()
        top.addWidget(QLabel("Status:"))
        top.addWidget(self.status_combo)
        top.addSpacing(10)
        top.addWidget(QLabel("検索:"))
        top.addWidget(self.keyword_edit, 1)
        top.addSpacing(10)
        top.addWidget(QLabel("件数:"))
        top.addWidget(self.limit_spin)
        top.addSpacing(10)
        top.addWidget(self.reload_btn)
        top.addWidget(self.export_btn)
        top.addSpacing(10)
        top.addWidget(self.open_btn)

        root.addLayout(top)
        root.addWidget(self.table, 1)

        self.setLayout(root)

        # --- イベント ---
        self.reload_btn.clicked.connect(self.reload)
        self.export_btn.clicked.connect(self.export_csv)
        self.open_btn.clicked.connect(self.pick_db)

        self.status_combo.currentIndexChanged.connect(self.reload)
        self.keyword_edit.returnPressed.connect(self.reload)
        self.limit_spin.valueChanged.connect(self.reload)

        # 初回ロード
        self.connect_db()
        self.reload()

    def connect_db(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

        if not self.db_path.exists():
            QMessageBox.warning(self, "DB Not Found", f"DBが見つかりません:\n{self.db_path}")
            return

        try:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
        except Exception as e:
            QMessageBox.critical(self, "DB Error", f"DB接続に失敗:\n{e}")

    def build_query(self):
        status = self.status_combo.currentText()
        keyword = self.keyword_edit.text().strip()
        limit = int(self.limit_spin.value())

        sql = """
        SELECT ts, status, pnn50, artist_name, track_name
        FROM events
        """

        where = []
        params = []

        if status != "ALL":
            where.append("status = ?")
            params.append(status)

        if keyword:
            where.append("(track_name LIKE ? OR artist_name LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like])

        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY ts DESC"
        sql += " LIMIT ?"
        params.append(limit)

        return sql, params

    def reload(self):
        if not self.conn:
            return

        # テーブル存在チェック（優しく）
        try:
            self.conn.execute("SELECT 1 FROM events LIMIT 1")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Table Error",
                "eventsテーブルが読めません。\n"
                "スキーマやDBパスを確認してね。\n\n"
                f"詳細: {e}",
            )
            return

        sql, params = self.build_query()

        try:
            rows = self.conn.execute(sql, params).fetchall()
        except Exception as e:
            QMessageBox.critical(self, "Query Error", f"クエリ失敗:\n{e}\n\nSQL:\n{sql}\n\nParams:\n{params}")
            return

        columns = ["ts", "status", "pnn50", "artist_name", "track_name"]

        header_labels = ["日時", "状態", "pNN50", "アーティスト", "曲名"]

        self.model = QStandardItemModel(0, len(columns))
        self.model.setHorizontalHeaderLabels(header_labels)


        for r in rows:
            items = []
            for h in columns:
                v = r[h]
                it = QStandardItem("" if v is None else str(v))
                # 数値列は右寄せ
                if h == "pnn50":
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                # 編集不可
                it.setEditable(False)
                items.append(it)
            self.model.appendRow(items)

        self.table.setModel(self.model)
        self.table.resizeColumnsToContents()

    def export_csv(self):
        if not self.conn:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVとして保存",
            str(Path.cwd() / "events_export.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return

        sql, params = self.build_query()
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"取得失敗:\n{e}")
            return

        columns = ["ts", "status", "pnn50", "artist_name", "track_name"]
        header_labels = ["日時", "状態", "pNN50", "アーティスト", "曲名"]

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header_labels)
                for r in rows:
                    w.writerow([r[c] for c in columns])

        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"CSV保存失敗:\n{e}")
            return

        QMessageBox.information(self, "Exported", f"CSVを書き出しました:\n{path}")

    def pick_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "SQLite DBを選択",
            str(self.db_path.parent if self.db_path else Path.cwd()),
            "SQLite DB (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if not path:
            return
        self.db_path = Path(path)
        self.connect_db()
        self.reload()


def main():
    app = QApplication(sys.argv)
    viewer = DbViewer(DEFAULT_DB_PATH)
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
