# Task 13 Report: UI — Chat Area

## Status: DONE

## Implementation

Created `shadowtalk/ui/widgets/chat_area.py` exactly as specified in the brief.

### File: `shadowtalk/ui/widgets/chat_area.py`

- `ChatArea(QWidget)` with `message_sent = Signal(str)`
- `_build_ui()`: QVBoxLayout containing a QListWidget (message list, spacing=2) and an input row (QLineEdit + QPushButton "发送")
- `_on_send()`: strips input, emits `message_sent`, clears input box; connected to both button click and Return key
- `add_message(text, role, timestamp)`: creates a MessageBubble, wraps it in a QListWidgetItem with size hint, adds to list, scrolls to bottom
- `show_loading()`: adds "正在回复…" loading bubble (role="loading"), tracks it in `_loading_item`, disables send button
- `hide_loading()`: removes the loading item by row, re-enables send button

### Self-review

- Code matches brief verbatim — no deviations.
- Imports and class structure consistent with sibling `MessageBubble` widget.
- Signal/slot connections are correct (clicked + returnPressed → `_on_send`).
- Loading state management correctly guards against double-removal via the `if self._loading_item` check.
- No TDD test required per brief (UI component only).

## Commits

- `741c44a` feat(ui): add ChatArea widget with message list and input box
