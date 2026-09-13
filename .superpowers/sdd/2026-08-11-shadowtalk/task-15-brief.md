# Task 15: UI — Main Window

**Files:**
- Create: `shadowtalk/ui/widgets/friend_list.py`
- Create: `shadowtalk/ui/widgets/friend_dialog.py`
- Create: `shadowtalk/ui/main_window.py`
- Create: `shadowtalk/main.py`

## Interfaces
- Consumes: all UI widgets, AIWorker, AIClient, memory_engine, repositories, Settings
- Produces: main application entry point

## Implementation

```python
# shadowtalk/ui/widgets/friend_list.py
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import Signal


class FriendListWidget(QWidget):
    friend_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list)
        self.add_btn = QPushButton("+ 新增好友")
        layout.addWidget(self.add_btn)

    def _on_item_clicked(self, item):
        friend_id = item.data(1000)
        if friend_id:
            self.friend_selected.emit(friend_id)

    def load_friends(self, friends: list):
        self.list.clear()
        for friend in friends:
            item = QListWidgetItem(friend["name"])
            item.setData(1000, friend["id"])
            self.list.addItem(item)
```

```python
# shadowtalk/ui/widgets/friend_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QHBoxLayout, QLabel, QFileDialog
)


class FriendDialog(QDialog):
    def __init__(self, parent=None, friend=None):
        super().__init__(parent)
        self.friend = friend
        self.avatar_path = friend["avatar_path"] if friend else ""
        self.setWindowTitle("新增好友" if friend is None else "编辑好友")
        self.setMinimumWidth(400)
        self._build_ui()
        if friend:
            self._fill_data(friend)

    def _build_ui(self):
        layout = QFormLayout()
        self.name_input = QLineEdit()
        layout.addRow("昵称：", self.name_input)
        self.remark_input = QLineEdit()
        layout.addRow("备注：", self.remark_input)
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("定义对方身份、性格、说话语气...")
        self.prompt_input.setMinimumHeight(120)
        layout.addRow("AI人设Prompt：", self.prompt_input)

        avatar_row = QHBoxLayout()
        self.avatar_label = QLabel("未选择")
        avatar_btn = QPushButton("选择头像")
        avatar_btn.clicked.connect(self._pick_avatar)
        avatar_row.addWidget(self.avatar_label)
        avatar_row.addWidget(avatar_btn)
        layout.addRow("头像：", avatar_row)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addRow(btn_row)

        wrapper = QVBoxLayout()
        wrapper.addLayout(layout)
        self.setLayout(wrapper)

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择头像", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.avatar_path = path
            self.avatar_label.setText(os.path.basename(path))

    def _fill_data(self, friend):
        self.name_input.setText(friend["name"])
        self.remark_input.setText(friend["remark"])
        self.prompt_input.setPlainText(friend["system_prompt"])

    def get_data(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "remark": self.remark_input.text().strip(),
            "system_prompt": self.prompt_input.toPlainText().strip(),
            "avatar_path": self.avatar_path,
        }
```

```python
# shadowtalk/ui/main_window.py
from PySide6.QtWidgets import QMainWindow, QSplitter, QMessageBox
from PySide6.QtCore import QTimer
from datetime import datetime

from shadowtalk.ui.widgets.friend_list import FriendListWidget
from shadowtalk.ui.widgets.chat_area import ChatArea
from shadowtalk.ui.widgets.friend_dialog import FriendDialog
from shadowtalk.ui.threads.ai_worker import AIWorker
from shadowtalk.core.memory_engine import build_context
from shadowtalk.core.ai_client import AIClient
from shadowtalk.core.friend_service import FriendService
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)
from shadowtalk.config.settings import Settings


def _now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ShadowTalk 影聊")
        self.resize(900, 600)
        self.current_friend_id = None
        self.ai_worker = None

        self.ai_client = AIClient(
            base_url=Settings.get("api_base_url"),
            api_key=Settings.get("api_key"),
            model=Settings.get("model_name"),
            temperature=Settings.get_float("temperature"),
            max_tokens=Settings.get_int("max_output_tokens"),
        )

        self.friend_list = FriendListWidget()
        self.chat_area = ChatArea()

        splitter = QSplitter()
        splitter.addWidget(self.friend_list)
        splitter.addWidget(self.chat_area)
        splitter.setSizes([200, 700])
        self.setCentralWidget(splitter)

        self.friend_list.friend_selected.connect(self._on_friend_selected)
        self.friend_list.add_btn.clicked.connect(self._on_add_friend)
        self.chat_area.message_sent.connect(self._on_message_sent)

        self.scanner = BackgroundScanner()
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scanner.scan_now)
        self.scan_timer.start(3600 * 1000)

        self._load_friends()

    def _load_friends(self):
        friends = FriendRepository.get_all()
        self.friend_list.load_friends(friends)

    def _on_friend_selected(self, friend_id: int):
        self.current_friend_id = friend_id
        self.chat_area.message_list.clear()
        self._load_history_messages(friend_id)

    def _load_history_messages(self, friend_id: int):
        msgs = MessageRepository.get_unarchived(friend_id)
        for m in msgs:
            self.chat_area.add_message(m["content"], m["sender_type"], m["create_time"])

    def _on_add_friend(self):
        dialog = FriendDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            FriendService.create(**data)
            self._load_friends()

    def _on_message_sent(self, text: str):
        if not self.current_friend_id:
            return

        self.chat_area.add_message(text, "user", _now_timestamp())
        MessageRepository.insert(
            self.current_friend_id, "user", text,
            self._next_round_index(self.current_friend_id)
        )

        self.chat_area.show_loading()
        self.ai_worker = AIWorker(
            self.current_friend_id, text,
            self.ai_client, build_context
        )
        self.ai_worker.finished.connect(self._on_ai_reply)
        self.ai_worker.failed.connect(self._on_ai_failed)
        self.ai_worker.start()

    def _on_ai_reply(self, reply: str):
        self.chat_area.hide_loading()
        self.chat_area.add_message(reply, "ai", _now_timestamp())
        MessageRepository.insert(
            self.current_friend_id, "ai", reply,
            self._current_round_index(self.current_friend_id)
        )

    def _on_ai_failed(self, error: str):
        self.chat_area.hide_loading()
        self.chat_area.add_message(f"回复失败：{error}", "ai", _now_timestamp())

    def _next_round_index(self, friend_id: int) -> int:
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return (row[0] or 0) + 1

    def _current_round_index(self, friend_id: int) -> int:
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return row[0] or 1
```

```python
# shadowtalk/main.py
import sys
import os

os.makedirs("data/avatars", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

from PySide6.QtWidgets import QApplication
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings
from shadowtalk.ui.main_window import MainWindow


def main():
    Database.get_connection()
    Settings.init_defaults()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    exit_code = app.exec()

    Database.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

## Notes
- UI components, no TDD tests
- Commit all files together
