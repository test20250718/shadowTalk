# Task 13: UI — Chat Area

**Files:**
- Create: `shadowtalk/ui/widgets/chat_area.py`

## Interfaces
- Consumes: `MessageBubble`
- Produces:
  - `ChatArea` widget with `message_sent` signal, `add_message()`, `show_loading()`, `hide_loading()`

## Implementation

```python
# shadowtalk/ui/widgets/chat_area.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Signal
from shadowtalk.ui.widgets.message_bubble import MessageBubble


class ChatArea(QWidget):
    message_sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading_item = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.message_list = QListWidget()
        self.message_list.setSpacing(2)
        layout.addWidget(self.message_list)

        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入消息...")
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send)
        self.input_box.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_box)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

    def _on_send(self):
        text = self.input_box.text().strip()
        if not text:
            return
        self.message_sent.emit(text)
        self.input_box.clear()

    def add_message(self, text: str, role: str, timestamp: str):
        bubble = MessageBubble(text, role, timestamp)
        item = QListWidgetItem()
        item.setSizeHint(bubble.sizeHint())
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, bubble)
        self.message_list.scrollToBottom()

    def show_loading(self):
        self.add_message("正在回复…", "loading", "")
        self._loading_item = self.message_list.item(self.message_list.count() - 1)
        self.send_btn.setEnabled(False)

    def hide_loading(self):
        if self._loading_item:
            row = self.message_list.row(self._loading_item)
            self.message_list.takeItem(row)
            self._loading_item = None
        self.send_btn.setEnabled(True)
```

## Notes
- UI component, no TDD test
- Commit after implementation
