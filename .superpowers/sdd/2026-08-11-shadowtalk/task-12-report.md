# Task 12 Report: UI — Message Bubble

## Status: DONE

## Commits
- `6b81e07` feat(ui): add MessageBubble widget

## Files Created
- `shadowtalk/ui/__init__.py` — empty package init
- `shadowtalk/ui/widgets/__init__.py` — empty package init
- `shadowtalk/ui/widgets/message_bubble.py` — MessageBubble widget

## Implementation Notes
- Implemented `MessageBubble` exactly per the brief.
- Constructor signature matches interface: `MessageBubble(text: str, role: str, timestamp: str, parent=None)`.
- Three roles handled:
  - `user` — right-aligned, `#DCF8C6` background, 12px border-radius
  - `ai` — left-aligned, `#ECECEC` background, 12px border-radius
  - `loading` — italic gray text, left-aligned
- Timestamp label centered above bubble, `#888` color, 11px font.
- Content label has `setWordWrap(True)`, `TextSelectableByMouse`, `setMaximumWidth(400)` — suitable for chat display in ChatArea (Task 13).

## Self-Review
- Code matches brief verbatim.
- Import guard: only depends on `PySide6.QtWidgets` and `PySide6.QtCore`.
- No logic errors; pure UI component with no external dependencies.
- No TDD test required (UI component, verified manually per brief).

## Concerns
None.
