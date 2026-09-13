# Task 14: UI — AI Worker Thread

**Files:**
- Create: `shadowtalk/ui/threads/__init__.py`
- Create: `shadowtalk/ui/threads/ai_worker.py`

## Interfaces
- Consumes: `memory_engine.build_context()`, `AIClient`
- Produces:
  - `AIWorker(QThread)` with `finished` and `failed` signals

## Implementation

```python
# shadowtalk/ui/threads/ai_worker.py
from PySide6.QtCore import QThread, Signal


class AIWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, friend_id, user_message, ai_client, memory_engine):
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.ai_client = ai_client
        self.memory_engine = memory_engine

    def run(self):
        try:
            messages = self.memory_engine.build_context(
                self.friend_id, self.user_message
            )
            reply = self.ai_client.chat(messages)
            self.finished.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))
```

## Notes
- UI thread worker, no TDD test
- Commit after implementation
