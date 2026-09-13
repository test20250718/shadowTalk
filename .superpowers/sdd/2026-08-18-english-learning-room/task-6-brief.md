# Task 6: UI — EnglishRoomWindow skeleton and layout

**Files to create:**
- `shadowtalk/ui/widgets/english_room.py`
- `tests/test_english_room.py`

**What to do:**

Create `shadowtalk/ui/widgets/english_room.py` with the `EnglishRoomWindow` class that extends `RoomWindow`:

```python
"""沉浸式英语教室：左聊右练，AI 驱动练习卡片。

复用 RoomWindow 骨架：左侧窄聊天区（280px）+ 右侧练习卡片面板。
AI 通过 present_exercise 工具在右侧出题，用户答题后结果回传 AI。
设计文档：docs/superpowers/specs/2026-08-18-english-learning-room-design.md
"""
import json
import logging
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QWidget, QButtonGroup, QRadioButton, QLineEdit,
)

from shadowtalk.core.english_exercise import (
    record_exercise, upsert_progress, get_stats,
)
from shadowtalk.ui.widgets.room_window import RoomBubble, RoomWindow

logger = logging.getLogger(__name__)


class ExerciseCard(QFrame):
    """练习卡片基类：题型渲染 + 答题回传"""

    answered = Signal(str, dict)  # (tool_call_id, result_dict)

    def __init__(self, exercise_data: dict, tool_call_id: str = "", parent=None):
        super().__init__(parent)
        self._data = exercise_data
        self._tool_call_id = tool_call_id
        self._start_time = time.time()
        self._attempts = 0
        self._answered = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(8)
        self.setStyleSheet("""
            QFrame { background-color: rgba(255,255,255,235);
                     border-radius: 16px; }
            QLabel { color: #1F2430; background: transparent; }
        """)


class EnglishRoomWindow(RoomWindow):
    """英语教室：左聊右练"""

    def __init__(self, friend_id: int, word_range: str = "CET-4",
                 start_mode: str = "restart", parent=None):
        self._word_range = word_range
        self._start_mode = start_mode
        self._current_card = None
        self._current_tool_call_id = ""
        super().__init__(friend_id, "english", parent=parent)

    def _build_ui(self):
        super()._build_ui()
        # 左侧聊天区固定 280px（和阅读室右边聊天区同宽）
        self.chat_scroll.setFixedWidth(280)
        # 右侧练习面板
        self.exercise_panel = QFrame()
        self.exercise_panel.setStyleSheet("background: transparent;")
        self._exercise_layout = QVBoxLayout(self.exercise_panel)
        self._exercise_layout.setContentsMargins(16, 16, 16, 16)
        self._exercise_layout.addStretch(1)
        # 插入到内容区右侧
        self._content_host.addWidget(self.exercise_panel, 1)
        # 统计标签（放在顶栏标题后）
        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(
            "color: rgba(245,239,230,210); font-size: 12px; background: transparent;")
        self._update_stats()

    def _update_stats(self):
        """刷新顶部统计"""
        stats = get_stats(self.friend_id)
        self._stats_label.setText(
            f"🔥 连胜 {stats['streak']}  |  "
            f"今日 {stats['today_count']} 题  |  "
            f"正确率 {stats['accuracy']}%")

    def _on_exercise_requested(self, code: str, word_range: str, reason: str):
        """AIWorker 发出 exercise_requested 信号时渲染卡片"""
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        try:
            data = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            logger.error("解析练习数据失败: %s", code[:100])
            return
        self._render_exercise_card(data)

    def _render_exercise_card(self, data: dict):
        """根据题型渲染对应卡片（Task 7 实现具体渲染）"""
        # 清除旧卡片
        if self._current_card is not None:
            self._exercise_layout.removeWidget(self._current_card)
            self._current_card.deleteLater()
            self._current_card = None
        # Task 7 will implement the actual card rendering
        placeholder = QLabel("练习卡片加载中…")
        placeholder.setStyleSheet("font-size: 14px; color: #7A7A7A;")
        self._exercise_layout.insertWidget(
            self._exercise_layout.count() - 1, placeholder)
        self._current_card = placeholder

    def closeEvent(self, event):
        if self._current_card is not None:
            self._current_card.deleteLater()
            self._current_card = None
        super().closeEvent(event)
```

**Tests for `tests/test_english_room.py`:**

```python
def test_english_room_window_class():
    """EnglishRoomWindow 应继承 RoomWindow"""
    from shadowtalk.ui.widgets.english_room import EnglishRoomWindow
    from shadowtalk.ui.widgets.room_window import RoomWindow
    assert issubclass(EnglishRoomWindow, RoomWindow)
```

**Verification:**
- `pytest tests/test_english_room.py -v` → PASS
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: add EnglishRoomWindow skeleton with layout`

**Context:** This is the UI skeleton. The actual exercise card rendering (5 types) is Task 7. This task establishes:
- Left chat (280px) + right exercise panel layout
- Stats display
- Exercise request signal handler (disables input during exercise)
- Placeholder card rendering (replaced in Task 7)
- Close event cleanup

The `ExerciseCard` class is defined as a stub — Task 7 will add the actual rendering logic for all 5 exercise types.
