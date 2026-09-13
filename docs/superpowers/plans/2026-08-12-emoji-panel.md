# 表情面板（Emoji Panel）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在聊天输入框旁添加笑脸按钮，点击展开/收起一个常用 Unicode emoji 网格面板，点击表情插入输入框光标处。

**Architecture:** 新组件 `EmojiPanel(QWidget)` 独立文件，通过 `emoji_selected = Signal(str)` 与 `ChatArea` 通信；面板内嵌在 `composer_layout` 中输入卡片上方，默认隐藏；表情以普通文本字符插入，消息链路零改动。

**Tech Stack:** PySide6（QtWidgets/QtCore），pytest（带 Qt 测试用 `qtbot` 可选，无则用 `QApplication` 手动事件模拟）。

## Global Constraints

- 仅使用 Unicode emoji 字符（非图片表情包）
- 一组约 48 个常用表情，单页网格，无分类标签页
- 颜色常量复用 `shadowtalk/ui/widgets/message_bubble.py` 中的 `SURFACE`、`BORDER`、`BG`、`MUTED`
- 表情插入输入框光标处，面板不自动收起（可连续点多个）
- 点击面板外部区域收起面板
- 依赖：PySide6>=6.6.0（已有），pytest>=8.0.0（已有）

---

### Task 1: 创建 EmojiPanel 组件（含信号与网格布局）

**Files:**
- Create: `shadowtalk/ui/widgets/emoji_panel.py`
- Test: `tests/test_emoji_panel.py`

**Interfaces:**
- Consumes: 无（仅依赖 PySide6 与 message_bubble 的颜色常量）
- Produces: `EmojiPanel(QFrame)`（注：继承 QFrame 而非 QWidget，使 QSS 选择器 `QFrame{}` 能命中、圆角卡片外观生效；经用户裁决修正），属性 `emoji_selected = Signal(str)`；模块级常量 `EMOJIS: list[str]`、`BTN_SIZE = 38`、`COLUMNS = 8`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_emoji_panel.py
"""EmojiPanel 组件测试"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from shadowtalk.ui.widgets.emoji_panel import EmojiPanel

app = QApplication.instance() or QApplication(sys.argv)


def test_panel_starts_hidden():
    panel = EmojiPanel()
    assert not panel.isVisible()


def test_click_emits_emoji_selected():
    panel = EmojiPanel()
    received = []
    panel.emoji_selected.connect(received.append)
    # 通过 findChildren 拿到第一个表情按钮并点击
    from PySide6.QtWidgets import QPushButton
    first_btn = panel.findChildren(QPushButton)[0]
    first_btn.click()
    assert len(received) == 1
    assert isinstance(received[0], str)
    assert len(received[0]) >= 1  # 是一个非空字符


def test_has_enough_emojis():
    from PySide6.QtWidgets import QPushButton
    panel = EmojiPanel()
    buttons = panel.findChildren(QPushButton)
    assert len(buttons) >= 48
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_emoji_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadowtalk.ui.widgets.emoji_panel'`

- [ ] **Step 3: 实现 EmojiPanel**

```python
# shadowtalk/ui/widgets/emoji_panel.py
"""
ShadowTalk 表情面板
点击输入框旁的笑脸按钮展开，点击表情插入输入框
"""
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton
from PySide6.QtCore import Signal, Qt
from shadowtalk.ui.widgets.message_bubble import SURFACE, BORDER, BG

# 48 个常用表情（笑脸 / 手势 / 爱心 / 日常）
EMOJIS = [
    "😀", "😄", "😁", "😂", "🤣", "😊", "😇", "🙂",
    "😉", "😍", "😘", "🥰", "😜", "🤪", "😎", "🤓",
    "🥳", "😢", "😭", "😤", "😡", "🥺", "😳", "🤔",
    "🤗", "🙄", "😴", "🤤", "😷", "🤒", "💪", "👏",
    "👍", "👎", "👌", "✌️", "🤝", "🙏", "👋", "💖",
    "💕", "💯", "🔥", "✨", "🎉", "🎂", "🌈", "🍀",
]

BTN_SIZE = 38
COLUMNS = 8


class EmojiPanel(QFrame):
    """常用表情网格面板"""

    emoji_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background-color: {BG};
            }}
        """)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(2)
        for i, emoji in enumerate(EMOJIS):
            btn = QPushButton(emoji)
            btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, e=emoji: self.emoji_selected.emit(e))
            grid.addWidget(btn, i // COLUMNS, i % COLUMNS)
        self.setFixedWidth(COLUMNS * BTN_SIZE + 20)

    def set_panel_visible(self, visible: bool):
        """显示/隐藏面板"""
        self.setVisible(visible)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_emoji_panel.py -v`
Expected: PASS（3 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/ui/widgets/emoji_panel.py tests/test_emoji_panel.py
git commit -m "feat: add EmojiPanel widget with emoji grid"
```

---

### Task 2: 接入 ChatArea（按钮、面板、插入与收起逻辑）

**Files:**
- Modify: `shadowtalk/ui/widgets/chat_area.py`（输入区构建 124-194 行区域、`eventFilter`、`__init__`）
- Test: `tests/test_emoji_panel.py`（追加 ChatArea 集成测试）

**Interfaces:**
- Consumes: `EmojiPanel.emoji_selected: Signal(str)`、`EmojiPanel.set_panel_visible(bool)`（Task 1 产出）
- Produces: `ChatArea` 新增实例属性 `self.emoji_btn`（笑脸按钮）、`self.emoji_panel`（EmojiPanel）；`_on_emoji_selected(emoji: str)` 私有方法

- [ ] **Step 1: 写失败测试**

在 `tests/test_emoji_panel.py` 追加：

```python
def test_chat_area_emoji_integration():
    """ChatArea 集成：点按钮切换面板，点表情插入输入框"""
    from shadowtalk.ui.widgets.chat_area import ChatArea
    from PySide6.QtWidgets import QPushButton

    area = ChatArea()
    assert hasattr(area, "emoji_btn")
    assert hasattr(area, "emoji_panel")

    # 初始隐藏
    assert not area.emoji_panel.isVisible()

    # 点按钮 → 展开
    area.emoji_btn.click()
    assert area.emoji_panel.isVisible()

    # 点表情 → 插入输入框
    area.emoji_panel.findChildren(QPushButton)[0].click()
    text = area.input_box.toPlainText()
    assert len(text) >= 1  # 有内容

    # 再点按钮 → 收起
    area.emoji_btn.click()
    assert not area.emoji_panel.isVisible()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_emoji_panel.py -v`
Expected: FAIL — `AttributeError: 'ChatArea' object has no attribute 'emoji_btn'`

- [ ] **Step 3: 实现接入**

修改 `shadowtalk/ui/widgets/chat_area.py`：

**3a.** 在 `__init__` 中（`self._build_ui()` 之后或之前均可，需在 `_build_ui` 内创建）添加实例属性初始化：在 `_build_ui` 的输入卡片布局 `input_layout` 中，`self.input_box` 之前插入笑脸按钮：

```python
        # 表情按钮（位于输入框左侧）
        self.emoji_btn = QPushButton("😊")
        self.emoji_btn.setFixedSize(30, 30)
        self.emoji_btn.setCursor(Qt.PointingHandCursor)
        self.emoji_btn.setToolTip("表情")
        self.emoji_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: {BG};
            }}
            QPushButton:checked {{
                background-color: {ACCENT_SOFT};
            }}
        """)
        self.emoji_btn.setCheckable(True)
        self.emoji_btn.clicked.connect(self._toggle_emoji_panel)
        input_layout.addWidget(self.emoji_btn, 0, Qt.AlignVCenter)
```

**3b.** 在 `composer_layout.addWidget(input_card)` **之前**创建并添加面板（使其位于输入卡片上方）：

```python
        # 表情面板（默认隐藏，位于输入卡片上方）
        from shadowtalk.ui.widgets.emoji_panel import EmojiPanel
        self.emoji_panel = EmojiPanel()
        self.emoji_panel.hide()
        self.emoji_panel.emoji_selected.connect(self._on_emoji_selected)
        composer_layout.addWidget(self.emoji_panel, 0, Qt.AlignLeft)
```

**3c.** 添加两个方法：

```python
    def _toggle_emoji_panel(self):
        """切换表情面板显示状态"""
        visible = not self.emoji_panel.isVisible()
        self.emoji_panel.setVisible(visible)
        self.emoji_btn.setChecked(visible)

    def _on_emoji_selected(self, emoji: str):
        """点击表情 → 插入输入框光标处"""
        self.input_box.setFocus()
        cursor = self.input_box.textCursor()
        cursor.insertText(emoji)
        self.input_box.setTextCursor(cursor)
```

**3d.** 在 `eventFilter` 中加外部点击收起逻辑（`eventFilter` 当前只处理键盘事件，需要扩展；该 filter 已安装在 `input_box` 上，改为同时处理面板外部点击——注意：`input_box` 的 eventFilter 无法捕获面板外点击，改为在 `ChatArea` 上安装 `self.installEventFilter` 并通过全局事件过滤在 `main_window` 层处理更简单。最简方案：在 `ChatArea.eventFilter` 前新增对 `QEvent.MouseButtonPress` 的处理，并给 `self` 安装 filter）：

在 `__init__` 末尾追加：

```python
        self.installEventFilter(self)  # 用于检测面板外部点击收起
```

修改 `eventFilter`：

```python
    def eventFilter(self, obj, event):
        """Enter 发送，Shift+Enter 换行；点击面板外部收起表情面板"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.MouseButtonPress:
            # 排除面板自身、面板子控件、笑脸按钮（按钮由 clicked 负责切换）
            if (self.emoji_panel.isVisible()
                    and obj is not self.emoji_btn
                    and not self.emoji_panel.isAncestorOf(obj)):
                self.emoji_panel.hide()
                self.emoji_btn.setChecked(False)
            return super().eventFilter(obj, event)
        if obj is self.input_box and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False
                else:
                    self._on_send()
                    return True
        return super().eventFilter(obj, event)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_emoji_panel.py -v`
Expected: PASS（5 个测试全过：Task 1 的 3 个 + Task 2 的 2 个）

- [ ] **Step 5: 手动冒烟测试**

Run: `python -m shadowtalk.main`
Expected: 程序启动；点笑脸按钮 → 面板在输入框上方展开；连续点多个表情 → 均插入输入框；点聊天区空白处 → 面板收起；发送 → 气泡显示 emoji；重启后历史消息 emoji 仍显示

- [ ] **Step 6: 提交**

```bash
git add shadowtalk/ui/widgets/chat_area.py tests/test_emoji_panel.py
git commit -m "feat: integrate emoji panel into chat input"
```

---

### Task 3: 回归验证与收尾

**Files:**
- Test: `tests/`（全量回归）

**Interfaces:**
- Consumes: 全部已有代码
- Produces: 无（验证任务）

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（现有 ~13 个测试文件 + 新增 test_emoji_panel.py）

- [ ] **Step 2: 确认无遗留引用**

Run: `grep -rn "emoji_panel\|emoji_btn" shadowtalk/ docs/superpowers/plans/ | grep -v "__pycache__"`
Expected: 仅 chat_area.py 中的接入点与测试文件引用，无死代码

- [ ] **Step 3: 提交（如有遗漏改动）**

```bash
git add -A
git commit -m "test: verify emoji panel regression" --allow-empty
```
