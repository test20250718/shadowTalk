# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ShadowTalk (影聊)** — a local-first AI desktop chat application built with PySide6 (Qt for Python). Users chat with AI "friends" (personas) in immersive themed rooms (café, music room, reading room, English classroom). The app features long-term memory via hierarchical summarization, an AI tool sandbox for code execution, email sync for digital twins, TTS voice playback, and English exercise tools.

- **Language**: Python 3.11+
- **UI Framework**: PySide6 (Qt6)
- **AI Backend**: OpenAI-compatible API (default: DeepSeek)
- **Database**: SQLite (single file, WAL mode)
- **Package**: PyInstaller for distribution (single-file Windows exe / Linux .deb)

## Common Commands

```bash
# Setup (Windows)
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Run the app
venv\Scripts\python shadowtalk\main.py

# Run all tests (excluding GUI tests that need display)
venv\Scripts\python -m pytest tests -q --ignore=tests/test_main_window.py

# Run a single test file
venv\Scripts\python -m pytest tests/test_ai_client.py -v

# Run a single test function
venv\Scripts\python -m pytest tests/test_database.py::TestDatabase::test_something -v

# Build Windows portable exe (runs tests first, aborts on failure)
build_exe.bat

# Build Linux .deb (run on target-arch Linux)
./build_deb.sh [version]
```

## Architecture

### Layered Design

The codebase follows a strict layering — dependencies flow downward only:

```
ui/ (PySide6 widgets, threads, dialogs)
  └── core/ (business logic, pure Python — no PySide6 imports)
        └── data/ (repositories, database)
              └── config/ (paths, settings, logging)
```

**Key rule**: `core/` and `data/` must NEVER import from `ui/` or PySide6. `tts_service.py` and `python_excore.py` enforce this explicitly — they are pure Python services consumed by the UI layer.

### Memory Engine (core/memory_engine.py + core/layers/)

The defining architectural feature. Chat context for the AI is assembled in 4 layers:

- **L3 (Persona)**: System prompt — AI role, user role, work directory, custom system prompt.
- **L2 (High-Level Summary)**: Merged summaries of expired batch summaries (capped at `l2_limit` entries).
- **L1 (Batch Summary)**: Rolling summaries of archived conversations (generated when raw messages exceed `raw_keep_max`).
- **L0 (Raw Messages)**: Unarchived recent messages.

Flow: `build_context()` → `check_and_archive()` → extract L3→L2→L1→L0 → token budget check → compress if over budget.

### Archiver + Summarizer (core/archiver.py, core/summarizer.py)

When raw message count exceeds `raw_keep_max`, the oldest `summary_batch_size` messages are summarized into an L1 batch summary and marked archived. Expired L1 summaries (older than `summary_valid_days`) are merged into L2 by `BackgroundScanner` (runs hourly via QTimer).

### AI Tool Sandbox (core/python_executor.py + core/sandbox_prelude.py)

Two-layer defense for AI-generated code execution:
1. **Static AST scan** (`scan_write_paths`): Detects writes outside the friend's work directory before execution → triggers UI approval dialog.
2. **Runtime audit hook** (`sandbox_prelude.py`): Installs `sys.addaudithook` in the subprocess to block any writes outside workdir/approved paths. This is the hard guarantee — AST scanning is UX-only.

Execution: subprocess with bundled Python runtime (frozen) or current interpreter (dev), 30s timeout, `-I` isolated mode.

### Email Sync for Digital Twins (core/mail_*.py)

Digital personas ("friends") can be synced via email:
- **MailComposer**: Packages chat history into emails with embedded short codes for session matching.
- **MailSender** (SMTP): Sends chat digests to the asset authorizer.
- **MailReceiver** (IMAP): Fetches replies, matches sessions via In-Reply-To/References/subject codes.
- **MailSyncScheduler**: Pure logic layer determining which friends are due for sync (daily/weekly/monthly/minute-test cycles).
- **RevocationService**: Recognizes `#作废授权#` tag or AI-classified revocation intent from authorizer.

### Digital Asset Encryption (core/crypto_service.py + core/aes_core.py)

Pure-Python AES-128-CTR + HMAC-SHA256 for encrypting "digital twin" asset bundles. Key derivation: PBKDF2(reverse(timestamp) + nonce + private_key). Format: `base64(version || timestamp || nonce || ctr_nonce || ciphertext || tag)`.

### Room System (core/room_service.py)

Immersive themed rooms (café / music / reading / English) are "scene skins" — conversation history is shared with the main chat (stored under the friend, not the room). Rooms inject a scene prompt after the L3 persona block via `build_room_context()`. Background images are per-(room, friend) pairs.

### Threading Model (ui/threads/)

All long-running work runs in `QThread` subclasses:
- `AIWorker`: AI chat with tools. Emits signals for approval requests, exercise requests (English), and activity updates. Supports cancellation via `terminate()` (not cooperative — openai sync calls can't be interrupted).
- `MailReceiveWorker` / `MailSendWorker`: Email sync workers.
- `TTSWorker`: Async TTS synthesis.

**Pattern**: Workers emit signals to the UI thread; UI uses `QEventLoop` for nested event loops when it must wait (e.g., approval dialog, exercise answer) without blocking the main thread.

### Database (data/database.py)

Singleton connection with WAL mode, auto-migration (`_migrate` adds missing columns on startup), and write lock for transactions. Schema defined as `SCHEMA` string — tables: `friends`, `chat_messages`, `batch_summary`, `high_level_summary`, `app_config`, `rooms`, `room_backgrounds`, `processed_emails`, `reading_progress`, `english_exercise_stats`, `english_progress`.

Scene prompts for the 4 default rooms are seeded/updated on every startup (version-controlled content, no user edit UI).

### Path Resolution (config/paths.py)

- **Windows frozen**: exe directory (portable).
- **Linux frozen**: `~/.shadowtalk` (/opt is not writable).
- **Dev**: current working directory.
- Resources (icons): `sys._MEIPASS` when frozen, repo root in dev.

### Theme System (ui/theme.py)

Single source of truth for colors — `Theme` dataclass with light/dark variants. `global_qss()` generates QSS from the current theme. **This module must not import any Qt classes** (pure data + string formatting).

## Testing

- Tests use pytest with a `conftest.py` fixture that creates a unique temp SQLite DB per test (autouse).
- `test_main_window.py` is excluded from default runs (requires display/Qt environment).
- Test files mirror source module names: `test_ai_client.py`, `test_database.py`, etc.

## Build & Distribution

- **Windows** (`build_exe.bat`): Runs tests → PyInstaller via `ShadowTalk.spec` → `dist/ShadowTalk.exe`. The spec bundles: Python 3.11 runtime (for AI tool subprocess, stdlib trimmed of test/idlelib/tkinter/distutils), `sandbox_prelude.py`. Excludes numpy/scipy/PIL/matplotlib/pulled transitively by openai.
- **Linux** (`build_deb.sh`): PyInstaller onedir → bundle Python runtime into `_internal/runtime/` → assemble `.deb` with `.desktop` file. Data goes to `~/.shadowtalk`.

## Conventions

- All file headers and key logic have Chinese comments explaining the "why" (design decisions, user-reported bugs that prompted the code). Read these comments before modifying behavior.
- User-facing strings are in Chinese (Simplified).
- Settings are stored as strings in `app_config` and parsed via `Settings.get_int()` / `get_float()` / `get_bool()` — all take string keys.
- `sender_type` in `chat_messages`: `'user'`, `'ai'`, or `'human_reply'` (real human reply via email).
- Version is defined in `shadowtalk/__init__.py` as `__version__`.
