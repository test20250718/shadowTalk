# Task 8: Integration — wire up main_window and room_window

**Files to modify:**
- `shadowtalk/ui/main_window.py`
- `shadowtalk/ui/widgets/room_window.py`
- `shadowtalk/ui/widgets/english_room.py` (signal wiring)

**What to do:**

1. **Add `english` to `_ROOM_ICONS`** in `shadowtalk/ui/widgets/room_window.py`:
```python
_ROOM_ICONS = {"cafe": "☕", "music": "🎵", "reading": "📖", "english": "🏫"}
```

2. **Add English room option to `_on_open_room()`** in `shadowtalk/ui/main_window.py`:

Change the dialog items list:
```python
room_key, ok = QInputDialog.getItem(
    self, "选择房间", "去哪个房间？",
    ["☕ 咖啡馆", "🎵 音乐室", "📖 阅读室", "🏫 英语教室"], 0, False)
```

Update key_map:
```python
key_map = {"☕ 咖啡馆": ("cafe", "请谁去喝咖啡？"),
           "🎵 音乐室": ("music", "请谁一起听歌？"),
           "📖 阅读室": ("reading", "请谁一起读书？"),
           "🏫 英语教室": ("english", "请谁一起学英语？")}
```

Add english instantiation (after the reading room branch, before the else):
```python
        elif room_key_id == "english":
            from shadowtalk.ui.widgets.english_word_range_dialog import EnglishWordRangeDialog
            from PySide6.QtWidgets import QDialog
            dlg = EnglishWordRangeDialog(parent=self, has_progress=False)
            if dlg.exec() != QDialog.Accepted:
                return
            word_range, start_mode = dlg.get_selected_range()
            from shadowtalk.ui.widgets.english_room import EnglishRoomWindow
            room = EnglishRoomWindow(friend_id, word_range=word_range,
                                     start_mode=start_mode, parent=self)
```

3. **Wire up exercise_requested signal** in `english_room.py`:

In `_build_ui()` or `_on_send()`, connect the worker's `exercise_requested` signal to `_on_exercise_requested`:

```python
    def _on_send(self):
        super()._on_send()
        if self.ai_worker is not None:
            self.ai_worker._word_range = self._word_range
            try:
                self.ai_worker.exercise_requested.connect(
                    self._on_exercise_requested)
            except RuntimeError:
                pass  # 已连接
```

4. **Place stats label in toolbar** — add `self._stats_label` to the toolbar layout so it's visible:
```python
top_l.addWidget(self._stats_label, 1)
```

**Verification:**
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass
- Manual smoke test: `python -m shadowtalk.main` → open English room dialog → select CET-4 → enter room → verify layout

**Commit message:** `feat: integrate english room into main window and room launcher`

**Context:** This is the integration task that wires everything together. After this task:
- User can select "🏫 英语教室" from the room menu
- Word range dialog appears
- EnglishRoomWindow opens with chat left + exercise panel right
- AI can call present_exercise → worker suspends → card renders → user answers → result sent back
