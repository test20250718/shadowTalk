# Task 15 Report: UI — Main Window + entry point

## Status: DONE

## Files Created (verbatim from brief)
1. `shadowtalk/ui/widgets/friend_list.py` — FriendListWidget (QListWidget + add button, `friend_selected` signal)
2. `shadowtalk/ui/widgets/friend_dialog.py` — FriendDialog (name/remark/prompt/avatar form, `get_data()`)
3. `shadowtalk/ui/main_window.py` — MainWindow assembling splitter layout, AIWorker wiring, hourly BackgroundScanner timer
4. `shadowtalk/main.py` — entry point: ensure data dirs, init DB + Settings, run QApp, cleanup

## Commits
- `5237065` feat(ui): assemble MainWindow and add entry point main.py

## Self-review

### Import verification (all resolve)
- `FriendListWidget`, `ChatArea`, `FriendDialog` — local widgets ✓
- `AIWorker` (`shadowtalk.ui.threads.ai_worker`) ✓
- `build_context` (`shadowtalk.core.memory_engine`) ✓
- `AIClient`, `FriendService`, `BackgroundScanner` ✓
- `FriendRepository`, `MessageRepository`, `SummaryRepository` ✓
- `Settings`, `Database` ✓

### Signature compatibility (all match)
- `AIClient.__init__(base_url, api_key, model, temperature=, max_tokens=)` ✓
- `AIWorker.__init__(friend_id, user_message, ai_client, memory_engine)` ✓
- `FriendService.create(name, remark, system_prompt, avatar_source_path=)` — dialog `get_data()` returns `avatar_path` key which maps correctly via `**data` ✓
- `BackgroundScanner.scan_now()` ✓
- `Settings.get / get_int / get_float / init_defaults` ✓
- `Database.get_connection / close` ✓
- `ChatArea.message_sent` signal, `message_list`, `add_message`, `show_loading`, `hide_loading` ✓

### Notes
- All 4 files copied verbatim from task brief — no deviations.
- Brief's `main_window.py` imports `QMessageBox` and `SummaryRepository` but does not use them (left as-is per "verbatim" instruction).
- UI components — no TDD tests per brief.
- App is now runnable via `python -m shadowtalk.main` (pending display/server environment).
