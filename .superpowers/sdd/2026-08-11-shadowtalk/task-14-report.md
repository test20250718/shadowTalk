# Task 14 Report: UI — AI Worker Thread

## Status: DONE

## What was done
1. Created `shadowtalk/ui/threads/__init__.py` (empty package init)
2. Created `shadowtalk/ui/threads/ai_worker.py` with `AIWorker(QThread)` exactly per brief:
   - `finished = Signal(str)` and `failed = Signal(str)` signals
   - `__init__` stores `friend_id`, `user_message`, `ai_client`, `memory_engine`
   - `run()` calls `memory_engine.build_context()` then `ai_client.chat()`, emits `finished(reply)` on success or `failed(str(e))` on exception

## Commits
- `ca5f0b4` feat(ui): add AIWorker thread for background AI calls

## Self-review
- Code matches brief verbatim
- Package init allows `from shadowtalk.ui.threads import AIWorker`
- No TDD test required per brief (UI thread worker)
- Signals are class-level attributes on QThread subclass — correct PySide6 pattern

## Concerns
None.
