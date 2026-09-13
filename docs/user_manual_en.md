# ShadowTalk · User Manual

> Local-first AI desktop chat application
> Version v1.4.1

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation & Launch](#2-installation--launch)
3. [Interface Overview](#3-interface-overview)
4. [Adding Friends](#4-adding-friends)
5. [Chatting](#5-chatting)
6. [Immersive Chat Rooms](#6-immersive-chat-rooms)
7. [Email Sync (Digital Twins)](#7-email-sync-digital-twins)
8. [Importing Digital Twin Assets](#8-importing-digital-twin-assets)
9. [Settings](#9-settings)
10. [Data & Privacy](#10-data--privacy)
11. [FAQ](#11-faq)
12. [Shortcuts & Tips](#12-shortcuts--tips)

---

## 1. Introduction

**ShadowTalk** is a local-first AI desktop chat application. You can create multiple AI friends (each with their own persona, memory, and voice) and chat with them in immersive scenes.

### Core Features

- **Local-first**: All messages, memories, and settings are stored locally in a SQLite database on your machine. Nothing is uploaded to any server.
- **Long-term memory**: The AI automatically compresses early conversations into hierarchical summaries, remembering your chat history across sessions.
- **Immersive scenes**: Themed environments like cafes, with background images and scene prompts for a more atmospheric conversation.
- **Voice playback**: AI replies can be automatically read aloud (based on Edge TTS).
- **AI tool sandbox**: The AI can execute Python code in an isolated environment to help you process files and generate documents.
- **Email sync**: Digital twins can communicate with you asynchronously via email, with replies automatically appearing in chat.

---

## 2. Installation & Launch

### Windows Portable Version

1. Download `ShadowTalk.exe`.
2. Double-click to run — no installation required.
3. On first launch, the database and configuration are created automatically.

> The data directory is located in the same folder as the exe (portable design, travels with your USB drive).

### Developer Version (from source)

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python shadowtalk\main.py
```

---

## 3. Interface Overview

The main window uses a three-column layout:

```
┌────────┬──────────────┬──────────────────────────┐
│Vertical│ Left Sidebar │ Right Main Area          │
│Tab Bar │ (Friend List)│ (Chat / Mail)            │
│        │              │                          │
│ Chat ▤ │  ▸ Friend A  │  ┌────────────────────┐  │
│ Mail ✉ │  ▸ Friend B  │  │ Message bubbles    │  │
│        │     + Add    │  │ Input box          │  │
│        │              │  └────────────────────┘  │
└────────┴──────────────┴──────────────────────────┘
```

- **Vertical Tab Bar** (leftmost): Switch between "Chat" and "Mail" modes.
- **Left Sidebar**: Friend list (shown in Chat mode), with an add button at the top.
- **Right Main Area**: Shows the conversation in Chat mode; shows the mail list in Mail mode.

The top menu bar has "Settings" and "Help" menus. The bottom status bar shows the current status and an AI output disclaimer.

---

## 4. Adding Friends

1. Click the **"+ Add Friend"** button at the bottom of the friend list.
2. Fill in the dialog:

| Field | Description |
|-------|-------------|
| Name | AI friend's name |
| Remark | Display name in the list (overrides name) |
| Avatar | Choose from local images |
| AI Role | Role the AI plays (e.g., "Barista", "Secretary") |
| User Role | Role you play (e.g., "Regular", "Boss") |
| Work Directory | Directory where the AI sandbox can read/write files |
| Voice | TTS voice (default: Xiaoxiao) |
| System Prompt | Defines the AI's personality, tone, and behavior rules |

3. Click "OK" to save.

> **Tip**: The more specific the system prompt, the better the AI's behavior matches your expectations.

---

## 5. Chatting

### Sending Messages

1. Click a friend in the left list.
2. Type a message in the input box at the bottom right, press **Enter** to send.
3. The AI will reply after thinking, shown as message bubbles.

### Voice Playback

- AI replies are automatically read aloud (can be disabled in Settings).
- Click the voice button on a message bubble to replay.

### Interruption & Retry

- If you send a new message while the AI is still replying, the old task is automatically interrupted.
- Network errors show "Reply failed" — simply retry.

### AI Tool Sandbox

When the AI needs to execute code (e.g., processing files, generating charts), a **write approval card** appears:

- Code written within the friend's "work directory" is automatically approved.
- Writing outside the directory requires your confirmation. Click "Allow" or "Deny".

---

## 6. Immersive Chat Rooms

Click the scene button at the top of the main interface, select a friend, and enter the **Cafe** scene.

- Scenes have independent background images and atmosphere prompts.
- Chat within a scene shares the same message history as regular chat with that friend.
- After closing the scene window, the main interface automatically refreshes to show the latest messages.

---

## 7. Email Sync (Digital Twins)

Digital twins can communicate with you asynchronously via email, ideal for slow-paced, deep exchanges.

### Configuring Email

Open "Settings > Mail Configuration" and fill in:

| Field | Description |
|-------|-------------|
| SMTP Server | Outgoing server (e.g., smtp.qq.com) |
| SMTP Port | Outgoing port (default: 587) |
| SMTP Username | Sender email |
| SMTP Password | Email authorization code (not login password) |
| IMAP Server | Incoming server (e.g., imap.qq.com) |
| IMAP Username | Recipient email |
| IMAP Password | Email authorization code |

### Sync Mechanism

- The app periodically checks due friends and packages new conversations into emails sent to the asset authorizer.
- When the authorizer replies, the app automatically fetches and inserts the reply into the corresponding friend's chat.
- Replies appear as "human" role bubbles in chat.

### Sync Cycle

Set when adding/editing friends: Daily / Weekly / Monthly.

---

## 8. Importing Digital Twin Assets

The app supports importing shared "digital twins":

1. Click the **"Import Twin"** button at the bottom of the friend list.
2. Paste the asset ciphertext.
3. Preview the decrypted twin information.
4. Confirm to import, automatically creating the corresponding friend.

> Assets are encrypted with AES-128-CTR + HMAC-SHA256; only parties holding the correct key can encrypt/decrypt.

### Authorization Revocation

If the twin's creator revokes authorization, that twin's chat is frozen (cannot continue sending), but message history is preserved.

---

## 9. Settings

Open via the top menu "Settings > API & Memory".

### API Configuration

| Field | Description | Default |
|-------|-------------|---------|
| API Address | OpenAI-compatible endpoint | https://api.longcat.chat/openai/v1 |
| API Key | API key | (enter your own) |
| Model Name | Model to use | LongCat-2.0 |
| Temperature | Output randomness (0-2) | 0.7 |
| Max Output Length | Max tokens per reply | 20000 |
| Tool Call Limit | Max tool calls per turn | 15 |
| Tool Execution Timeout | Timeout per tool execution (seconds) | 120 |

> Multiple API configurations can be added in the "API Configuration" tab (add/delete/switch). The toolbar dropdown allows quick switching of the active model.

### Memory Parameters

| Field | Description |
|-------|-------------|
| Raw Message Keep | Recent rounds to keep uncompressed |
| Batch Size | Rounds per batch before summary compression |
| Summary Valid (days) | Batch summaries expire and merge into high-level summaries |
| Summary Target Chars | Target length for L1 summaries |
| Max Context Tokens | Max context sent to the AI per request |
| L2 Limit | Max high-level summaries to retain |

### Mail Configuration

See [7. Email Sync](#7-email-sync-digital-twins).

---

## 10. Data & Privacy

### Data Storage

| Data Type | Location |
|-----------|----------|
| Database | Data directory / shadowtalk.db |
| Avatars | Data directory / avatars/ |
| Prompt Logs | Data directory / prompt_logs/ |
| Mail Attachments | Data directory / mail_attachments/ |

### Privacy Principles

- **Local-first**: All data is stored locally; the app does not connect to any telemetry/statistics servers.
- **AI Calls**: Messages are sent to the configured AI endpoint, handled by that service provider.
- **Portable**: The Windows portable version stores all data next to the exe; deleting it erases everything.

### Backup & Migration

- Copy the entire data directory to back up.
- Move the data directory to the same relative location on another computer to restore.

---

## 11. FAQ

**Q: Missing DLL error on first launch?**
A: Install Visual C++ Redistributable 2015-2022 (x64).

**Q: AI replies "Initialization failed"?**
A: Check that the API address, key, and model name are correct; check network connectivity.

**Q: AI suddenly stops talking (empty bubble)?**
A: The model may have returned empty content. Try resending, or switch to a different model.

**Q: Not receiving email replies?**
A: Check that the IMAP configuration is correct; confirm IMAP is enabled on the email service; check that the authorization code is valid.

**Q: How to switch between dark/light theme?**
A: Click the theme toggle button in the toolbar.

**Q: How to completely delete all data?**
A: Close the app and delete the data directory. This operation cannot be undone — back up first.

---

## 12. Shortcuts & Tips

| Action | Description |
|--------|-------------|
| Enter | Send message |
| Shift + Enter | New line in input box |
| Click avatar | View/edit friend info |

### Tips

- **Persona writing**: Clearly define the AI's personality, catchphrases, and behavioral boundaries in the system prompt for more stable results.
- **Work directory**: Assign independent work directories to each friend to avoid interference when the AI executes code.
- **Memory tuning**: If the AI can't remember things, increase "Raw Message Keep" or "Max Context Tokens".
- **Tool sandbox**: When using code execution for the first time, pay attention to the approval card prompts and confirm safety before allowing.

---

> AI output is for reference only. Please verify before relying on it.
>
> ShadowTalk · Let AI friends live on your computer.
