# Task 12: UI — Message Bubble

**Files:**
- Create: `shadowtalk/ui/__init__.py`
- Create: `shadowtalk/ui/widgets/__init__.py`
- Create: `shadowtalk/ui/widgets/message_bubble.py`

## Interfaces
- Consumes: nothing (pure UI component)
- Produces:
  - `MessageBubble(text: str, role: str, timestamp: str, parent=None)`

## Implementation

```python
# shadowtalk/ui/widgets/message_bubble.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt


class MessageBubble(QWidget):
    def __init__(self, text: str, role: str, timestamp: str, parent=None):
        super().__init__(parent)
        self._role = role
        self._build_ui(text, role, timestamp)

    def _build_ui(self, text, role, timestamp):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)

        time_label = QLabel(timestamp)
        time_label.setStyleSheet("color: #888; font-size: 11px;")
        time_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(time_label)

        row = QHBoxLayout()
        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setMaximumWidth(400)
        content.setContentsMargins(10, 6, 10, 6)

        if role == "user":
            content.setStyleSheet(
                "background-color: #DCF8C6; border-radius: 12px; padding: 8px;"
            )
            row.addStretch()
            row.addWidget(content)
        elif role == "ai":
            content.setStyleSheet(
                "background-color: #ECECEC; border-radius: 12px; padding: 8px;"
            )
            row.addWidget(content)
            row.addStretch()
        else:  # loading
            content.setStyleSheet(
                "color: #888; font-style: italic; padding: 8px;"
            )
            row.addWidget(content)
            row.addStretch()

        main_layout.addLayout(row)
```

## Notes
- This is a pure UI component with no TDD test (UI components verified manually)
- Commit after implementation
