# Task 5 Report: Memory Layers (L0-L3)

## Status: DONE

## Commits
- `be1afd3` feat: add memory layer extractors (L0-L3)

## Files Created
- `shadowtalk/core/layers/__init__.py` — package init, re-exports l3/l2/l1/l0
- `shadowtalk/core/layers/l3_persona.py` — L3 persona extractor
- `shadowtalk/core/layers/l2_summary.py` — L2 high-level summary extractor
- `shadowtalk/core/layers/l1_summary.py` — L1 valid batch summary extractor
- `shadowtalk/core/layers/l0_raw.py` — L0 unarchived raw message extractor
- `tests/test_layers.py` — 8 tests covering all 4 layers

## Test Summary
- 8/8 layer tests pass; full suite 31/31 pass (no regressions).
- TDD cycle observed: tests failed on import (missing modules) → implemented → all green.

## Implementation Notes
- All four `extract(friend_id)` functions match the brief verbatim.
- `__init__.py` uses relative imports (`from . import ...`) to avoid circular import.
- Each returns `list[dict]` with `role`, `content`, `layer` keys.
- L3 returns `role="system"` with the friend's `system_prompt` (empty string if none).
- L2/L1 return `role="system"` for all entries.
- L0 maps `sender_type` directly to role (`"user"` or `"ai"`).
- L1 honors `Settings.get_int("summary_valid_days")` for expiration.

## Concerns
None.
