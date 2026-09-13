# Task 11: Friend Service — Report

## Status: DONE

## Commits
- `0f61f58` feat(shadowtalk): add FriendService for CRUD with avatar handling

## Test Summary
3 tests written (test_create_friend, test_create_with_avatar, test_delete_with_cascade) — all PASS.

## Files Created
- `shadowtalk/core/friend_service.py` — FriendService with create/delete/update_avatar
- `tests/test_friend_service.py` — 3 tests covering basic create, avatar copy+move, cascade delete

## Verification
- TDD cycle followed: tests written first, confirmed FAIL (ModuleNotFoundError), then implementation added, confirmed PASS.
- `core/friend_service.py` does NOT import PySide6 (constraint satisfied).
- Uses `Database.transaction()` for atomic cascade deletes.
- Avatar files copied to `data/avatars/{friend_id}/`.

## Concerns
- Pre-existing Windows file-locking issue in `conftest.py` causes `PermissionError` during teardown (test DB cannot be deleted while connection open). Tests themselves pass (3 passed, 3 teardown errors). Not introduced by this task; affects all shadowtalk tests on Windows.
