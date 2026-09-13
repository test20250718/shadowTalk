# 阅读室（沉浸式第三间）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"阅读室"：左书右聊 PDF 共读窗口，发问时按需把"当前页+前几页+章节标题"注入她的上下文，进度续读，底栏带精简环境音乐条。

**Architecture:** 继承咖啡馆 `RoomWindow` 骨架（同音乐室模式）。基类抽"内容区宿主"供插书页区；播放器本体从音乐室提取为共享 `MusicPlayerBar`；PDF 渲染用 PySide6 自带 QtPdf，文字提取用 pypdf；新表 `reading_progress` 记 (好友, 书) → 页码。

**Tech Stack:** PySide6 6.11.1（QtPdf/QtPdfWidgets）、pypdf 6.15.0、SQLite（现有 Database）。

**设计文档:** `docs/superpowers/specs/2026-08-17-reading-room-design.md`

## Global Constraints

- **零新依赖**：只用已装的 PySide6 6.11.1 与 pypdf 6.15.0（均已实测可用）
- 工作目录 `c:\work\aiworkspace18`，Python 3.11，测试命令 `python -m pytest <文件> -v`
- 测试**禁止真实联网与真实发声**：沿 `tests/test_music_room.py` 的 monkeypatch 套路（假 Worker、stub 播放器、类级阻断 `_fetch_lyrics`）
- 涉及真实书的集成测试用 `@needs_book`（`skipif` 本机无该文件），书路径：
  `C:\work\aiworkspace12\novels\PDF合集\西游记的正确打开方式.pdf`
- **QtPdf API 事实（已离屏验证，照抄勿改）**：
  - `QPdfView.PageMode.MultiPage`（不是 `Multi`）、`QPdfView.ZoomMode.FitToWidth`
  - 导航：`nav = view.pageNavigator()`；`nav.jump(page0, QPointF(0, 0))`（0 基页码）；`nav.currentPage()`（0 基）；信号 `nav.currentPageChanged(int)`
  - 加载成败**不要**用 `doc.load()` 的返回值判断（成功成员是 `Error.None_`，Python 里别扭）；用 `doc.status() == QPdfDocument.Status.Ready` / `Status.Error`
- 场景人设必须点名"阅读室"并写明"不是咖啡馆"（历史教训：她会说错房间）
- UI 文案全部中文；每个任务结束一次 git commit（在 `c:\work\aiworkspace18` 下执行，git 仓库根在 `c:\work`）

## 文件总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `shadowtalk/core/reading_service.py` | 新建 | 章节反查/滑动窗口（纯函数）、PdfTextSource（pypdf 懒提取）、进度 CRUD |
| `shadowtalk/data/database.py` | 修改 | reading_progress 建表 + 'reading' 房间播种 |
| `shadowtalk/ui/widgets/music_player_bar.py` | 新建 | 共享播放条（含 TTS 避让接线、compact 形态） |
| `shadowtalk/ui/widgets/music_room.py` | 修改 | 播放逻辑换成 MusicPlayerBar，保留歌词/取词/打轴 |
| `shadowtalk/ui/widgets/room_window.py` | 修改 | 内容区宿主、`_show_user_message` 钩子、📖 图标 |
| `shadowtalk/ui/widgets/reading_room.py` | 新建 | ReadingRoomWindow |
| `shadowtalk/ui/main_window.py` | 修改 | 房间选择加阅读室入口 |
| `tests/test_reading_service.py` | 新建 | 服务层测试 |
| `tests/test_music_player_bar.py` | 新建 | 播放条测试 |
| `tests/test_music_room.py` | 修改 | 13 个测试改指向 `win.music_bar.*` |
| `tests/test_reading_room.py` | 新建 | 窗口测试 |
| `tests/test_room_window.py` | 修改 | 追加内容区宿主/钩子测试 |

---

### Task 1: reading_service 纯函数（章节反查 + 滑动窗口）

**Files:**
- Create: `shadowtalk/core/reading_service.py`
- Test: `tests/test_reading_service.py`

**Interfaces:**
- Consumes: 无（纯函数，不依赖 Qt/pypdf）
- Produces（Task 3/7 依赖）:
  - `find_chapter_title(page_text: Callable[[int], str], page: int, max_back: int = 10) -> str`（1 基页码；空串=没找到）
  - `build_window_text(page_text: Callable[[int], str], page: int, page_count: int, before: int = 4) -> str`（全部页空 → `""`；个别空页 → `（第N页无法提取）` 占位）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_reading_service.py`：

```python
"""阅读室服务测试：章节反查、滑动窗口（纯函数部分）"""
import sys
from pathlib import Path

import pytest

from shadowtalk.data.database import Database
from shadowtalk.data.repositories import FriendRepository

Database.get_connection()   # 触发迁移（Task 2 会加 reading_progress）

BOOK = Path(r"C:\work\aiworkspace12\novels\PDF合集\西游记的正确打开方式.pdf")
needs_book = pytest.mark.skipif(not BOOK.is_file(), reason="本机无目标书")


def _make_friend(name="小读"):
    return FriendRepository.insert(name, "", "你是小读")


# ── 章节反查 ──

def test_chapter_title_found_on_same_page():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {5: "第2章 寿命即货币\n满堂议论声嗡嗡作响。"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 5) == "第2章 寿命即货币"


def test_chapter_title_scan_backward():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {10: "第1章 开端\n正文", 15: "正文若干" * 50}
    assert find_chapter_title(lambda p: pages.get(p, ""), 15) == "第1章 开端"


def test_chapter_title_prefers_chapter_over_volume():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {8: "第一卷：三界资本格局构建\n第1章 说书人开讲\n正文"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 9) == "第1章 说书人开讲"


def test_chapter_title_volume_only_fallback():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {8: "第一卷：三界资本格局构建\n正文"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 9) == "第一卷：三界资本格局构建"


def test_chapter_title_not_found_returns_empty():
    from shadowtalk.core.reading_service import find_chapter_title
    assert find_chapter_title(lambda p: "正文" * 100, 50) == ""


# ── 滑动窗口 ──

def test_window_text_joins_pages():
    from shadowtalk.core.reading_service import build_window_text
    pages = {96: "甲", 97: "乙", 98: "丙", 99: "丁", 100: "戊"}
    assert build_window_text(lambda p: pages.get(p, ""), 100, 360) == "甲\n乙\n丙\n丁\n戊"


def test_window_text_clamps_at_first_page():
    from shadowtalk.core.reading_service import build_window_text
    assert build_window_text(lambda p: f"P{p}", 2, 360) == "P1\nP2"


def test_window_text_marks_failed_pages():
    from shadowtalk.core.reading_service import build_window_text
    pages = {1: "有字"}
    text = build_window_text(lambda p: pages.get(p, ""), 3, 360)
    assert "（第2页无法提取）" in text
    assert "（第3页无法提取）" in text
    assert text.startswith("有字")


def test_window_text_all_empty_for_scan():
    from shadowtalk.core.reading_service import build_window_text
    assert build_window_text(lambda p: "", 100, 360) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: FAIL（`ModuleNotFoundError: shadowtalk.core.reading_service`）

- [ ] **Step 3: 写实现**

新建 `shadowtalk/core/reading_service.py`（本任务只写两个纯函数 + 常量，其余 Task 2/3 再加）：

```python
# shadowtalk/core/reading_service.py
"""阅读室服务：PDF 文本提取（懒加载）、章节标题反查、滑动窗口组装、
共读进度存取。

按需阅读（设计 2026-08-17）：用户翻页她不读不语；发问时才现场组装
"当前页+前几页+章节标题"进场景上下文。零预读、零翻页监听。
"""
import re

# 章节标题：页首出现的「第X章/回/节/卷 标题」整行
_CHAPTER_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千零两]+[章回节卷][^\n]{0,30})$", re.M)
_FINE_LEVELS = ("章", "回", "节")   # 粒度优先于「卷」
_SCAN_HEAD_CHARS = 600              # 只在页首找标题
_MAX_BACK_PAGES = 10                # 章节反查最多回看页数
_WINDOW_BEFORE = 4                  # 滑动窗口：当前页往前几页


def find_chapter_title(page_text, page: int,
                       max_back: int = _MAX_BACK_PAGES) -> str:
    """从 page 页起往回找最近的章节标题；找不到返回空串。

    page_text: (1 基页码) -> 该页文本。同一页既有「章/回/节」又有
    「卷」时取前者（更细粒度）；同页多条取最后一条（最靠近正文）。
    """
    for p in range(page, max(1, page - max_back) - 1, -1):
        head = page_text(p)[:_SCAN_HEAD_CHARS]
        matches = _CHAPTER_RE.findall(head)
        fine = [m for m in matches if any(k in m for k in _FINE_LEVELS)]
        if fine:
            return fine[-1].strip()
        if matches:
            return matches[-1].strip()
    return ""


def build_window_text(page_text, page: int, page_count: int,
                      before: int = _WINDOW_BEFORE) -> str:
    """滑动窗口：第 page-before..page 页正文连排。

    全部页都提不到文本 → 空串（调用方按扫描件处理）；
    个别空页以「（第N页无法提取）」占位。
    """
    parts, any_text = [], False
    for p in range(max(1, page - before), page + 1):
        if p > page_count:
            break
        t = page_text(p).strip()
        if not t:
            parts.append(f"（第{p}页无法提取）")
        else:
            any_text = True
            parts.append(t)
    return "\n".join(parts) if any_text else ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/reading_service.py tests/test_reading_service.py
git commit -m "feat: reading service chapter lookup and sliding window text"
```

---

### Task 2: DB 迁移（reading_progress 表 + 'reading' 房间播种）与进度 CRUD

**Files:**
- Modify: `shadowtalk/data/database.py`
- Modify: `shadowtalk/core/reading_service.py`（追加 CRUD）
- Test: `tests/test_reading_service.py`（追加）

**Interfaces:**
- Consumes: `Database.get_connection()/transaction()`（现有）
- Produces（Task 6/7 依赖，定义在 reading_service）:
  - `save_progress(friend_id: int, book_path: str, page: int) -> None`
  - `get_progress(friend_id: int, book_path: str) -> int | None`
  - `last_book(friend_id: int) -> tuple[str, int] | None`（最近读的 (路径, 页码)）
- 依赖的 DB 事实：`rooms` 表播种走 `INSERT OR IGNORE` + `UPDATE ... scene_prompt`（database.py:135-150 模式）

- [ ] **Step 1: 写失败测试**

在 `tests/test_reading_service.py` 末尾追加：

```python
# ── 进度存取与房间播种（Task 2）──

def test_progress_roundtrip_and_last_book():
    from shadowtalk.core import reading_service as rs
    fid = _make_friend()
    assert rs.get_progress(fid, "D:/books/a.pdf") is None
    rs.save_progress(fid, "D:/books/a.pdf", 12)
    assert rs.get_progress(fid, "D:/books/a.pdf") == 12
    rs.save_progress(fid, "D:/books/a.pdf", 13)      # 同本书翻页更新
    assert rs.get_progress(fid, "D:/books/a.pdf") == 13
    assert rs.last_book(fid) == ("D:/books/a.pdf", 13)
    rs.save_progress(fid, "D:/books/b.pdf", 1)       # 换一本 → 最近的是 b
    assert rs.last_book(fid) == ("D:/books/b.pdf", 1)
    assert rs.get_progress(fid, "D:/books/a.pdf") == 13   # 旧书进度还在


def test_reading_room_seeded():
    from shadowtalk.core.room_service import get_room
    room = get_room("reading")
    assert room is not None
    assert room["name"] == "阅读室"
    assert "阅读室" in room["scene_prompt"]
    assert "不是咖啡馆" in room["scene_prompt"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 新增 2 个 FAIL（`no such table: reading_progress`；`get_room("reading")` 返回 None）；Task 1 的 9 个仍 PASS

- [ ] **Step 3: 写实现**

3a. `shadowtalk/data/database.py`：在 `_MUSIC_SCENE_PROMPT`（约 21-28 行）之后追加场景人设常量：

```python
# 阅读室场景人设：安静陪读，按需阅读（当前页正文由界面动态追加）
_READING_SCENE_PROMPT = (
    "【当前场景：阅读室】你现在和对方并肩坐在阅读室里一起读书——"
    "注意这是阅读室，不是咖啡馆；即使你们之前在咖啡馆或音乐室聊过，"
    "此刻也已经换到阅读室了。你们在读同一本书：用户翻到哪里，"
    "你只能通过界面给出的当前页附近正文了解剧情，看不到更多。"
    "安静陪读：用户不提问你就安静陪着，不主动说话、不剧透、不点评。"
    "用户发问时，像朋友一样聊书里的内容，回答口语化。"
    "用户问到给定正文之外的内容时，如实说你还没读到那里。"
    "不使用列表、标题或长篇大论。"
)
```

3b. 同文件 SCHEMA 字符串里、`room_backgrounds` 表（约 94-100 行）之后追加：

```sql
CREATE TABLE IF NOT EXISTS reading_progress (
    friend_id INTEGER NOT NULL,
    book_path TEXT NOT NULL,
    page INTEGER NOT NULL DEFAULT 1,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (friend_id, book_path)
);
```

3c. 同文件 `_migrate` 里、music 的 `UPDATE rooms ...`（约 149-150 行）之后追加：

```python
        conn.execute(
            "INSERT OR IGNORE INTO rooms (key, name, scene_prompt) "
            "VALUES ('reading', '阅读室', ?)",
            (_READING_SCENE_PROMPT,),
        )
        conn.execute("UPDATE rooms SET scene_prompt=? WHERE key='reading'",
                     (_READING_SCENE_PROMPT,))
```

3d. `shadowtalk/core/reading_service.py` 末尾追加：

```python
# ── 共读进度（reading_progress：每好友每本书记一页码）──

from shadowtalk.data.database import Database


def save_progress(friend_id: int, book_path: str, page: int) -> None:
    with Database.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reading_progress "
            "(friend_id, book_path, page) VALUES (?, ?, ?)",
            (friend_id, book_path, page))


def get_progress(friend_id: int, book_path: str) -> int | None:
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT page FROM reading_progress "
        "WHERE friend_id=? AND book_path=?",
        (friend_id, book_path)).fetchone()
    return row["page"] if row else None


def last_book(friend_id: int) -> tuple[str, int] | None:
    """该好友最近读的书 (路径, 页码)；没读过返回 None。

    update_time 只有秒级精度，同秒并列时用 rowid 决胜（后写者胜）。
    """
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT book_path, page FROM reading_progress WHERE friend_id=? "
        "ORDER BY update_time DESC, rowid DESC LIMIT 1",
        (friend_id,)).fetchone()
    return (row["book_path"], row["page"]) if row else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/data/database.py shadowtalk/core/reading_service.py tests/test_reading_service.py
git commit -m "feat: reading_progress table, reading room seed, progress CRUD"
```

---

### Task 3: PdfTextSource（pypdf 懒提取 + 缓存）

**Files:**
- Modify: `shadowtalk/core/reading_service.py`（追加类）
- Test: `tests/test_reading_service.py`（追加）

**Interfaces:**
- Consumes: pypdf 6.15.0（`from pypdf import PdfReader`）
- Produces（Task 6/7 依赖）:
  - `class PdfTextSourceError(Exception)`
  - `class PdfTextSource: __init__(self, path: str)`（打不开抛 `PdfTextSourceError`）；属性 `page_count: int`；方法 `page_text(self, page: int) -> str`（1 基页码，越界/异常页返回 `""`）——`src.page_text` 本身就是纯函数要的 `Callable[[int], str]`

- [ ] **Step 1: 写失败测试**

在 `tests/test_reading_service.py` 末尾追加：

```python
# ── PDF 文本源（Task 3）──

def test_text_source_error_on_bad_path():
    from shadowtalk.core.reading_service import PdfTextSource, PdfTextSourceError
    with pytest.raises(PdfTextSourceError):
        PdfTextSource(r"C:\nonexistent\bad.pdf")


@needs_book
def test_text_source_real_book():
    from shadowtalk.core.reading_service import PdfTextSource
    src = PdfTextSource(str(BOOK))
    assert src.page_count == 360
    assert "寿命即货币" in src.page_text(11)
    assert src.page_text(0) == ""        # 越界页空串
    assert src.page_text(999) == ""
    # 缓存：同页第二次取值一致
    assert src.page_text(11) == src.page_text(11)


@needs_book
def test_chapter_lookup_real_book():
    from shadowtalk.core.reading_service import PdfTextSource, find_chapter_title
    src = PdfTextSource(str(BOOK))
    assert "第22章" in find_chapter_title(src.page_text, 100)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 新增 3 个 FAIL（`ImportError: cannot import name 'PdfTextSource'`）；旧的 11 个仍 PASS

- [ ] **Step 3: 写实现**

`shadowtalk/core/reading_service.py`：顶部 import 区加 `from pypdf import PdfReader`，文件末尾追加：

```python
# ── PDF 文本源：懒提取 + 内存缓存（同页只提一次）──


class PdfTextSourceError(Exception):
    """PDF 打不开 / 提不了文本"""


class PdfTextSource:
    """给"按需阅读"供正文：发问时才取页文本，毫秒级、不预载全书。"""

    def __init__(self, path: str):
        try:
            self._reader = PdfReader(path)
        except Exception as e:
            raise PdfTextSourceError(f"PDF 打不开：{e}") from e
        self.path = path
        self.page_count = len(self._reader.pages)
        self._cache: dict[int, str] = {}

    def page_text(self, page: int) -> str:
        """1 基页码 → 文本；越界/提取异常页返回空串。"""
        if page < 1 or page > self.page_count:
            return ""
        if page not in self._cache:
            try:
                self._cache[page] = \
                    self._reader.pages[page - 1].extract_text() or ""
            except Exception:
                self._cache[page] = ""
        return self._cache[page]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 14 PASS（无书的机器上 2 个 SKIP + 12 PASS）

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/reading_service.py tests/test_reading_service.py
git commit -m "feat: PdfTextSource lazy pypdf extraction with cache"
```

---

### Task 4: 提取共享 MusicPlayerBar（音乐室重构 + 测试改指）

**Files:**
- Create: `shadowtalk/ui/widgets/music_player_bar.py`
- Modify: `shadowtalk/ui/widgets/music_room.py`
- Create: `tests/test_music_player_bar.py`
- Modify: `tests/test_music_room.py`

**Interfaces:**
- Consumes: `shadowtalk.ui.widgets.tts_player.get_player()`（现有 TTS 单例，信号 `playback_started/finished/failed/synthesis_failed`）
- Produces（Task 6 依赖）:
  - `class MusicPlayerBar(QFrame): __init__(self, parent=None, compact: bool = False)`
  - 信号 `song_changed = Signal(int)`（播放曲目索引变化）
  - `current_title(self) -> str`；`play_at(self, index: int)`（清单循环回绕）；`stop(self)`；`add_control(self, btn)`
  - 内部件沿用音乐室旧名（音乐室歌词逻辑与测试依赖）：`_player, _audio, _playlist, _current_index, _base_volume, _ducked, _pick_btn, _prev_btn, _play_btn, _next_btn, _song_label, _volume_slider`，方法 `_on_volume(v), _duck(), _unduck(), _toggle_play(), _on_pick_music(), _refresh_song_label(extra), _on_media_status, _on_media_error`
  - `compact=True`：隐藏 `_prev_btn/_next_btn/_song_label`，歌名进 `_play_btn` 的 tooltip（阅读室环境音乐形态）
- MusicRoomWindow 重构后对外不变的部分：`current_song_title()`、`_current_scene_prompt()`、`parse_lrc`、`LrcMakerDialog(self)` 用法；新增委托属性 `_playlist/_current_index/_player`（转发到 `self.music_bar`，LrcMaker 与测试依赖）

- [ ] **Step 1: 写失败测试（新组件）**

新建 `tests/test_music_player_bar.py`：

```python
"""共享播放条 MusicPlayerBar 测试（从音乐室提取）"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication.instance() or QApplication(sys.argv)


def test_bar_full_mode_controls():
    from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
    bar = MusicPlayerBar()
    bar.show()
    assert not bar._prev_btn.isHidden()
    assert not bar._next_btn.isHidden()
    assert not bar._song_label.isHidden()
    bar.close()


def test_bar_compact_mode_hides_extras():
    from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
    bar = MusicPlayerBar(compact=True)
    bar.show()
    assert bar._prev_btn.isHidden()
    assert bar._next_btn.isHidden()
    assert bar._song_label.isHidden()
    assert not bar._pick_btn.isHidden()
    assert not bar._volume_slider.isHidden()
    bar.close()


def test_bar_song_changed_and_title_loop():
    from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
    bar = MusicPlayerBar()

    class _NoPlay:                       # 阻断真实发声
        def __getattr__(self, name):
            return lambda *a, **k: None
    bar._player = _NoPlay()
    bar._playlist = [Path("D:/s/晴天.mp3"), Path("D:/s/七里香.flac")]
    fired = []
    bar.song_changed.connect(lambda i: fired.append(i))
    bar.play_at(1)
    assert fired == [1]
    assert bar.current_title() == "七里香"
    bar.play_at(2)                       # 越界回绕到 0
    assert bar.current_title() == "晴天"
    assert fired == [1, 0]


def test_bar_duck_volume():
    """避让：她开口压到 30%，避让中调音量仍按比例，说完恢复"""
    from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
    bar = MusicPlayerBar()
    bar._on_volume(80)
    bar._duck()
    assert abs(bar._audio.volume() - 0.8 * 0.3) < 1e-9
    bar._on_volume(90)
    assert abs(bar._audio.volume() - 0.9 * 0.3) < 1e-9
    bar._unduck()
    assert abs(bar._audio.volume() - 0.9) < 1e-9


def test_bar_add_control_inserts_between_next_and_label():
    from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
    bar = MusicPlayerBar()
    b1, b2 = QPushButton("词"), QPushButton("✍")
    bar.add_control(b1)
    bar.add_control(b2)
    lay = bar.layout()
    assert lay.indexOf(bar._next_btn) < lay.indexOf(b1) < lay.indexOf(b2) \
        < lay.indexOf(bar._song_label)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_music_player_bar.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 新建 MusicPlayerBar**

新建 `shadowtalk/ui/widgets/music_player_bar.py`（代码整体从 `music_room.py` 迁来，变化：组件化、`compact`、`song_changed`、TTS 避让接线移入、新增 `add_control`）：

```python
# shadowtalk/ui/widgets/music_player_bar.py
"""可复用迷你音乐条：选曲、连播循环、播放控制、音量、TTS 自动避让。

从音乐室提取（阅读室设计 2026-08-17）：播放器本体两房共用；
歌词同步/联网取词/打轴制作仍音乐室专属。
compact=True 为精简形态（阅读室环境音乐）：只留选曲+播放/暂停+音量。
"""
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
)

from shadowtalk.ui.widgets.tts_player import get_player

logger = logging.getLogger(__name__)

_AUDIO_FILTER = "音乐 (*.mp3 *.flac *.wav *.ogg *.m4a *.aac *.wma)"
_DUCK_FACTOR = 0.3   # 她说话时音乐压低到 30%


class MusicPlayerBar(QFrame):
    """播放条组件：内部持有 QMediaPlayer，TTS 避让已接线（宿主零接线）。

    常用：current_title() / play_at(i) / stop() / add_control(btn)。
    内部件（_player/_playlist/…）保留音乐室旧名，供歌词逻辑与测试使用。
    """
    song_changed = Signal(int)   # 播放曲目索引变化（选曲/切歌/连播都发）

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._playlist = []      # [Path]
        self._current_index = -1
        self._base_volume = 60   # 用户设的音量（避让恢复的目标值）
        self._ducked = False

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(self._base_volume / 100.0)
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_media_error)

        # TTS 避让接线在组件内完成：她开口 → 音乐压低；说完 → 恢复
        tts = get_player()
        tts.playback_started.connect(self._duck)
        tts.playback_finished.connect(self._unduck)
        tts.playback_failed.connect(self._unduck)
        tts.synthesis_failed.connect(self._unduck)

        self._build_ui()

    # ── UI ──
    def _build_ui(self):
        box = QHBoxLayout(self)
        if self._compact:
            self.setStyleSheet("background: transparent;")
            box.setContentsMargins(0, 4, 0, 4)
        else:
            self.setStyleSheet("background-color: rgba(20,16,12,150);")
            box.setContentsMargins(18, 6, 14, 6)

        def btn(text, tip, slot):
            b = QPushButton(text)
            b.setFixedSize(32, 32)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setAutoDefault(False)
            b.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,40); color: #F5EFE6;
                              border: none; border-radius: 16px; font-size: 14px; }
                QPushButton:hover { background: rgba(255,255,255,90); }
            """)
            b.clicked.connect(slot)
            return b

        self._pick_btn = btn("🎵", "加载本地音乐到播放清单", self._on_pick_music)
        self._prev_btn = btn("⏮", "上一首",
                             lambda: self.play_at(self._current_index - 1))
        self._play_btn = btn("▶", "播放 / 暂停", self._toggle_play)
        self._next_btn = btn("⏭", "下一首",
                             lambda: self.play_at(self._current_index + 1))
        self._song_label = QLabel("还没选歌 —— 点 🎵 加载本地音乐")
        self._song_label.setStyleSheet(
            "color: rgba(245,239,230,220); font-size: 12px; background: transparent;")
        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._base_volume)
        self._volume_slider.setMaximumWidth(160)
        self._volume_slider.setToolTip("音乐音量（她说话时自动压低，说完恢复）")
        self._volume_slider.setStyleSheet("""
            QSlider::sub-page:horizontal { background: rgba(46,158,87,200);
                                          border-radius: 2px; }
            QSlider::add-page:horizontal { background: rgba(255,255,255,60);
                                          border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0;
                                        background: #2E9E57; border-radius: 6px; }
        """)
        self._volume_slider.valueChanged.connect(self._on_volume)

        box.addWidget(self._pick_btn)
        box.addWidget(self._prev_btn)
        box.addWidget(self._play_btn)
        box.addWidget(self._next_btn)
        self._controls_tail = box.count()   # add_control 的插入点
        box.addWidget(self._song_label, 1)
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("color: rgba(245,239,230,220); font-size: 12px;"
                               " background: transparent;")
        box.addWidget(vol_icon)
        box.addWidget(self._volume_slider)

        if self._compact:
            for w in (self._prev_btn, self._next_btn, self._song_label):
                w.hide()

    def add_control(self, btn: QPushButton) -> None:
        """房间专属按钮（音乐室：词/✍）插到播放控制之后、歌名之前"""
        self.layout().insertWidget(self._controls_tail, btn)
        self._controls_tail += 1

    # ── 对外 API ──
    def current_title(self) -> str:
        if 0 <= self._current_index < len(self._playlist):
            return self._playlist[self._current_index].stem
        return ""

    def play_at(self, index: int):
        if not self._playlist:
            return
        index %= len(self._playlist)          # 循环清单：越界回绕
        self._current_index = index
        self._player.setSource(
            QUrl.fromLocalFile(str(self._playlist[index])))
        self._player.play()
        self._play_btn.setText("⏸")
        self._refresh_song_label()
        self.song_changed.emit(index)

    def stop(self):
        self._player.stop()

    # ── 内部（名称沿用音乐室旧名）──
    def _on_pick_music(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "加载本地音乐到播放清单", "", _AUDIO_FILTER)
        if not paths:
            return
        added = [Path(p) for p in paths]
        was_empty = not self._playlist
        self._playlist.extend(added)
        self._refresh_song_label(f"已加入 {len(added)} 首")
        if was_empty:                      # 第一批选曲 → 自动开始播
            self.play_at(0)

    def _refresh_song_label(self, extra: str = ""):
        total = len(self._playlist)
        song = self.current_title()
        if not total:
            text = "还没选歌 —— 点 🎵 加载本地音乐"
        elif song:
            pos = f"{self._current_index + 1}/{total}"
            text = f"♪ {song}  ({pos})"
            text = f"{text} {extra}" if extra else text
        else:
            text = f"清单 {total} 首 {extra}".strip()
        self._song_label.setText(text)
        if song:
            # 精简模式歌名不占位，进播放键 tooltip
            self._play_btn.setToolTip(f"{text}（点击暂停）")

    def _toggle_play(self):
        if not self._playlist:
            self._on_pick_music()
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.setText("▶")
            self._play_btn.setToolTip("播放")
        else:
            if self._current_index < 0:
                self.play_at(0)
            else:
                self._player.play()
                self._play_btn.setText("⏸")
                self._play_btn.setToolTip("暂停")

    def _on_media_status(self, status):
        # 一首播完 → 自动下一首（清单循环）
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_at(self._current_index + 1)

    def _on_media_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        logger.error("音乐播放失败: %s", error_string)
        self._refresh_song_label(f"（播放失败：{error_string}）")

    def _on_volume(self, value: int):
        self._base_volume = value
        # 避让中调音量也即时生效（按避让比例），滑条手感不滞后
        factor = _DUCK_FACTOR if self._ducked else 1.0
        self._audio.setVolume(value / 100.0 * factor)

    def _duck(self, _msg_id=None):
        """她开口说话 → 音乐压低"""
        self._ducked = True
        self._audio.setVolume(self._base_volume / 100.0 * _DUCK_FACTOR)

    def _unduck(self, _msg_id=None):
        self._ducked = False
        self._audio.setVolume(self._base_volume / 100.0)
```

- [ ] **Step 4: 跑新组件测试确认通过**

Run: `python -m pytest tests/test_music_player_bar.py -v`
Expected: 5 PASS

- [ ] **Step 5: 重构音乐室用播放条**

把 `shadowtalk/ui/widgets/music_room.py` 整体重写为（删除全部迁走的播放器代码，保留歌词部分；`parse_lrc`/`_LyricFetcher` 原样保留）：

```python
# shadowtalk/ui/widgets/music_room.py
"""沉浸式音乐室：本地音乐播放清单 + 并肩听歌聊天

播放器本体在共享组件 MusicPlayerBar（阅读室同款，2026-08-17 提取）；
音乐室专属：LRC 歌词同步、LRCLIB 联网取词、打轴制作。
"""
import json
import logging
import re
import threading
from urllib.parse import quote
from urllib.request import urlopen

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
from shadowtalk.ui.widgets.room_window import RoomWindow

logger = logging.getLogger(__name__)

_LRC_TIME_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_LRC_API = "https://lrclib.net/api/search?q="


def parse_lrc(text: str) -> list[tuple[int, str]]:
    """解析 LRC 歌词为 [(毫秒, 歌词行)]，按时间升序。

    支持一行多时间标签（[00:12.0][01:30.5]副歌）；跳过元数据行
    （[ti:][ar:] 等非时间格式）与空行。
    """
    lines = []
    for line in text.splitlines():
        stamps = _LRC_TIME_RE.findall(line)
        if not stamps:
            continue
        content = _LRC_TIME_RE.sub("", re.sub(r"\[[^\]]*\]", "", line)).strip()
        if not content:
            continue
        for mm, ss in stamps:
            lines.append((int(mm) * 60000 + int(float(ss) * 1000), content))
    lines.sort(key=lambda t: t[0])
    return lines


class _LyricFetcher(QObject):
    """后台线程查 LRCLIB 开放歌词库（queued signal 回主线程）"""
    fetched = Signal(int, str)   # (请求时的曲目索引, LRC 文本或空串)

    def __init__(self, index: int, title: str):
        super().__init__()
        self._index = index
        self._title = title

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        text = ""
        try:
            url = _LRC_API + quote(self._title)
            with urlopen(url, timeout=8) as resp:
                hits = json.loads(resp.read().decode("utf-8"))
            for hit in hits if isinstance(hits, list) else []:
                synced = hit.get("syncedLyrics")
                if synced and synced.strip():
                    text = synced
                    break
        except Exception as e:
            logger.warning("歌词获取失败: %s %s", self._title, e)
        self.fetched.emit(self._index, text)


class MusicRoomWindow(RoomWindow):
    """音乐室：咖啡馆骨架 + 音乐播放（播放条为共享组件）"""

    def __init__(self, friend_id: int, parent=None):
        super().__init__(friend_id, "music", parent=parent)

        # 播放条（完整形态）：TTS 避让已在组件内接线
        self.music_bar = MusicPlayerBar(self)

        # 音乐室专属按钮插到播放控制之后
        def room_btn(text, tip, slot):
            b = QPushButton(text)
            b.setFixedSize(32, 32)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setAutoDefault(False)
            b.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,40); color: #F5EFE6;
                              border: none; border-radius: 16px; font-size: 14px; }
                QPushButton:hover { background: rgba(255,255,255,90); }
            """)
            b.clicked.connect(slot)
            return b

        self._lyric_btn = room_btn(
            "词", "联网获取这首歌的歌词（LRCLIB）",
            lambda: self._fetch_lyrics(force=True))
        self._lrc_maker_btn = room_btn(
            "✍", "制作歌词：边听边打轴（自创歌曲）", self._on_open_lrc_maker)
        self.music_bar.add_control(self._lyric_btn)
        self.music_bar.add_control(self._lrc_maker_btn)

        # 切歌/连播 → 加载对应歌词；播放位置驱动逐句高亮
        self.music_bar.song_changed.connect(
            lambda _i: self._load_lyrics_for_current())
        self.music_bar._player.positionChanged.connect(self._on_position)

        # 歌词：右侧居中，逐句同步（同名 .lrc 存在时才显示）
        self._lyrics = []          # [(ms, line)]
        self._lyric_index = -1
        self._fetched_keys = set()  # 已联网查过歌词的曲目（避免重复请求）
        self._lyric_label = QLabel(self)
        self._lyric_label.setStyleSheet(
            "color: rgba(255,252,245,235); font-size: 18px;"
            "background: transparent;")
        self._lyric_label.setAlignment(Qt.AlignCenter)
        self._lyric_label.setWordWrap(True)
        self._lyric_label.hide()

        self._pre_input_host.addWidget(self.music_bar)

    # ── 播放器件委托（LrcMaker 与歌词逻辑依赖旧属性名）──
    @property
    def _playlist(self):
        return self.music_bar._playlist

    @_playlist.setter
    def _playlist(self, v):
        self.music_bar._playlist = v

    @property
    def _current_index(self):
        return self.music_bar._current_index

    @_current_index.setter
    def _current_index(self, v):
        self.music_bar._current_index = v

    @property
    def _player(self):
        return self.music_bar._player

    @_player.setter
    def _player(self, v):
        self.music_bar._player = v

    def current_song_title(self) -> str:
        return self.music_bar.current_title()

    # ── 场景人设：注入当前歌名（她可以聊正在放的歌）──
    def _current_scene_prompt(self) -> str:
        base = super()._current_scene_prompt()
        song = self.current_song_title()
        if song:
            return f"{base}\n正在播放的歌曲：《{song}》。"
        return base

    def _on_open_lrc_maker(self):
        """打开歌词制作（边听边打轴）——自创歌曲网上搜不到词时用"""
        if not (0 <= self._current_index < len(self._playlist)):
            return
        from shadowtalk.ui.widgets.lrc_maker import LrcMakerDialog
        LrcMakerDialog(self).exec()

    # ── LRC 歌词同步 ──
    def _load_lyrics_for_current(self):
        """自动加载与歌曲同名的 .lrc（晴天.mp3 ↔ 晴天.lrc）"""
        self._lyrics = []
        self._lyric_index = -1
        if 0 <= self._current_index < len(self._playlist):
            lrc = self._playlist[self._current_index].with_suffix(".lrc")
            try:
                if lrc.is_file():
                    self._lyrics = parse_lrc(
                        lrc.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                logger.warning("歌词读取失败: %s %s", lrc, e)
        if self._lyrics:
            self._lyric_label.setText(self._lyrics[0][1])
            self._lyric_index = 0
            self._lyric_label.adjustSize()
            self._reposition_lyrics()
            self._lyric_label.show()
            self._lyric_label.raise_()
        else:
            self._lyric_label.hide()
            # 本地无 .lrc → 后台查 LRCLIB（每曲只自动查一次；手动「词」可重查）
            self._fetch_lyrics(force=False)

    def _fetch_lyrics(self, force: bool):
        """联网查歌词：找到 → 存同名 .lrc 并立即显示（之后永久本地可用）"""
        if not (0 <= self._current_index < len(self._playlist)):
            return
        key = str(self._playlist[self._current_index])
        if not force:
            if key in self._fetched_keys:
                return
            self._fetched_keys.add(key)
        else:
            self.music_bar._refresh_song_label("获取歌词中…")

        def on_fetched(index: int, text: str):
            if index != self._current_index or not text:
                if index == self._current_index and not text:
                    self.music_bar._refresh_song_label("（未找到带时间轴的歌词）")
                return
            lrc_path = self._playlist[index].with_suffix(".lrc")
            try:
                lrc_path.write_text(text, encoding="utf-8")
            except OSError as e:
                logger.warning("歌词保存失败: %s %s", lrc_path, e)
                return
            if index == self._current_index:
                self._load_lyrics_for_current()
                self.music_bar._refresh_song_label("歌词已就绪")

        fetcher = _LyricFetcher(self._current_index,
                                self._playlist[self._current_index].stem)
        fetcher.fetched.connect(on_fetched)
        fetcher.start()

    def _on_position(self, ms: int):
        """播放位置驱动歌词逐句同步"""
        if not self._lyrics:
            return
        idx = self._lyric_index
        # 向前找：还在当前句
        if idx >= 0 and idx < len(self._lyrics) and ms < self._lyrics[idx][0]:
            idx = -1
        # 顺序推进到当前句（句数少，线性足够）
        while (idx + 1 < len(self._lyrics)
               and self._lyrics[idx + 1][0] <= ms):
            idx += 1
        if idx != self._lyric_index and 0 <= idx < len(self._lyrics):
            self._lyric_index = idx
            self._lyric_label.setText(self._lyrics[idx][1])
            self._lyric_label.adjustSize()
            self._reposition_lyrics()

    def _reposition_lyrics(self):
        """歌词固定在窗口右侧垂直居中（不占布局，浮于背景之上）"""
        w = max(int(self.width() * 0.34), 220)
        x = self.width() - w - 40
        y = (self.height() - self._lyric_label.height()) // 2
        self._lyric_label.setGeometry(x, max(y, 120), w,
                                      self._lyric_label.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._lyric_label is not None and self._lyric_label.isVisible():
            self._reposition_lyrics()

    def closeEvent(self, event):
        self.music_bar.stop()
        super().closeEvent(event)
```

- [ ] **Step 6: 改音乐室测试指向 music_bar**

`tests/test_music_room.py` 逐处替换（其余不动）：

`test_music_room_window_controls_exist` 改为：

```python
def test_music_room_window_controls_exist():
    """音乐室有播放控制条：选曲/上一首/播放/下一首/歌名/音量滑条"""
    from shadowtalk.ui.widgets.music_room import MusicRoomWindow
    fid = _make_friend()
    win = MusicRoomWindow(fid)
    assert win.music_bar._pick_btn is not None
    assert win.music_bar._prev_btn is not None
    assert win.music_bar._play_btn is not None
    assert win.music_bar._next_btn is not None
    assert win.music_bar._volume_slider is not None
    assert "音乐室" in win.windowTitle()
    win.close()
```

`test_music_room_playlist_add_and_title` 改为：

```python
def test_music_room_playlist_add_and_title():
    """加载本地音乐到播放清单：歌名可查询（播放本体在共享播放条）"""
    from shadowtalk.ui.widgets.music_room import MusicRoomWindow
    fid = _make_friend()
    win = MusicRoomWindow(fid)

    class _NoPlay:  # 阻断真实发声：setSource 后不 play
        def __getattr__(self, name):
            return lambda *a, **k: None
    win.music_bar._player = _NoPlay()
    win.music_bar._playlist = [Path("D:/songs/晴天.mp3"),
                               Path("D:/songs/七里香.flac")]
    win.music_bar._current_index = 1
    assert win.current_song_title() == "七里香"

    win.music_bar._current_index = 0
    assert win.current_song_title() == "晴天"
    scene = win._current_scene_prompt()
    assert scene.endswith("《晴天》。")
    # 房间身份必须点名且明确压制"咖啡"惯性（用户报告：音乐室里她说成咖啡室）
    assert "音乐室" in scene
    assert "不是咖啡馆" in scene
```

`test_music_room_duck_on_tts` 改为：

```python
def test_music_room_duck_on_tts(monkeypatch):
    """自动避让：她开口（TTS playback_started）→ 音乐压低到 30%，说完恢复"""
    from shadowtalk.ui.widgets import room_window as rw
    from shadowtalk.ui.widgets.music_room import MusicRoomWindow
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = MusicRoomWindow(fid)

    volumes = []
    orig_set = win.music_bar._audio.setVolume
    monkeypatch.setattr(win.music_bar._audio, "setVolume",
                        lambda v: (volumes.append(v), orig_set(v)))

    win.music_bar._on_volume(80)           # 用户设音量 80
    assert volumes[-1] == 0.8
    win.music_bar._duck()                  # 她开口
    assert abs(volumes[-1] - 0.8 * 0.3) < 1e-9
    win.music_bar._unduck()                # 说完
    assert volumes[-1] == 0.8
    win.close()
```

`test_music_room_duck_respects_user_volume_during_tts` 改为：

```python
def test_music_room_duck_respects_user_volume_during_tts():
    """避让期间用户拉高音量：不立即生效到全量（仍以避让比例），结束后按新值恢复"""
    from shadowtalk.ui.widgets.music_room import MusicRoomWindow
    fid = _make_friend()
    win = MusicRoomWindow(fid)

    volumes = []
    orig_set = win.music_bar._audio.setVolume
    win.music_bar._audio.setVolume = lambda v: (volumes.append(v), orig_set(v))

    win.music_bar._duck()
    win.music_bar._on_volume(90)           # 说话中调音量 → 保持避让
    assert volumes[-1] == 0.9 * 0.3
    win.music_bar._unduck()
    assert volumes[-1] == 0.9
    win.close()
```

歌词/打轴各测试里三处机械替换（函数名与断言不动）：
- `win._player = _Stub()` → `win.music_bar._player = _Stub()`（各 `_StubPlayer` 同理）
- `win._playlist = [song]` → `win.music_bar._playlist = [song]`
- `win._play_at(0)` → `win.music_bar.play_at(0)`

涉及：`test_lyrics_sync_by_position`、`test_no_lrc_hides_lyrics`、`test_lyrics_positioned_right_center`、`test_lrc_maker_mark_and_save`。

- [ ] **Step 7: 跑全部音乐相关测试**

Run: `python -m pytest tests/test_music_player_bar.py tests/test_music_room.py -v`
Expected: 5 + 13 = 18 PASS

- [ ] **Step 8: Commit**

```bash
git add shadowtalk/ui/widgets/music_player_bar.py shadowtalk/ui/widgets/music_room.py tests/test_music_player_bar.py tests/test_music_room.py
git commit -m "refactor: extract shared MusicPlayerBar from music room"
```

---

### Task 5: 基类内容区宿主 + 用户消息钩子 + 阅读室图标

**Files:**
- Modify: `shadowtalk/ui/widgets/room_window.py:32`（图标表）
- Modify: `shadowtalk/ui/widgets/room_window.py:186-187`（内容区宿主）
- Modify: `shadowtalk/ui/widgets/room_window.py:309-316`（`_on_send` 加钩子调用）
- Modify: `shadowtalk/ui/widgets/room_window.py`（新增钩子方法）
- Test: `tests/test_room_window.py`（追加）

**Interfaces:**
- Consumes: 无新依赖
- Produces（Task 6/7 依赖）:
  - `self._content_host: QHBoxLayout`（含 `chat_scroll`，子类可 `insertWidget(0, w, stretch)` 往左插内容）
  - `def _show_user_message(self, text: str)`（基类空实现；阅读室覆盖为流式气泡；`_on_send` 落库后调用）
  - `_ROOM_ICONS["reading"] = "📖"`

- [ ] **Step 1: 写失败测试**

在 `tests/test_room_window.py` 末尾追加（沿用该文件已有的 QApplication/导入）：

```python
def test_content_host_wraps_chat_and_user_hook():
    """内容区宿主默认只含聊天区；用户消息钩子默认空实现不抛错"""
    from shadowtalk.data.repositories import FriendRepository
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = FriendRepository.insert("宿主测试", "", "测试")
    win = RoomWindow(fid, "cafe")
    assert win._content_host.count() == 1
    assert win._content_host.indexOf(win.chat_scroll) == 0
    win._show_user_message("你好")   # 咖啡馆不显示用户消息，静默即可
    win.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_room_window.py -v`
Expected: 新增 1 个 FAIL（`AttributeError: _content_host`）；原有全 PASS

- [ ] **Step 3: 改基类**

`shadowtalk/ui/widgets/room_window.py` 三处：

3a. 图标表（第 32 行）：

```python
_ROOM_ICONS = {"cafe": "☕", "music": "🎵", "reading": "📖"}
```

3b. `_build_ui` 中，把

```python
        self.chat_scroll.setWidget(self.chat_host)
        layout.addWidget(self.chat_scroll, 1)
```

替换为：

```python
        self.chat_scroll.setWidget(self.chat_host)
        # 内容区宿主：默认只有聊天区（咖啡馆/音乐室不变）；
        # 子类可往里插内容（阅读室在左侧插书页区）
        self._content_host = QHBoxLayout()
        self._content_host.setContentsMargins(0, 0, 0, 0)
        self._content_host.addWidget(self.chat_scroll, 1)
        layout.addLayout(self._content_host, 1)
```

3c. `_on_send` 中，`MessageRepository.insert(...)` 之后插一行：

```python
        MessageRepository.insert(self.friend_id, "user", text,
                                 self._next_round_index())
        self._show_user_message(text)
```

并在类中新增方法（放在 `_show_ai_reply` 附近）：

```python
    def _show_user_message(self, text: str):
        """用户消息上屏钩子：咖啡馆/音乐室不显示（只显示她的回复），
        阅读室覆盖为流式气泡（讨论要能看到双方的话）"""
```

- [ ] **Step 4: 跑房间全部测试（回归）**

Run: `python -m pytest tests/test_room_window.py tests/test_music_room.py tests/test_music_player_bar.py tests/test_room_service.py -v`
Expected: 全 PASS（基类改动对咖啡馆/音乐室零行为变化）

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/ui/widgets/room_window.py tests/test_room_window.py
git commit -m "refactor: RoomWindow content host + user-message hook + reading icon"
```

---

### Task 6: ReadingRoomWindow 窗口壳（书页区、翻页、续读、防抖、边界）

**Files:**
- Create: `shadowtalk/ui/widgets/reading_room.py`
- Test: `tests/test_reading_room.py`

**Interfaces:**
- Consumes:
  - Task 1-3: `reading_service.PdfTextSource / PdfTextSourceError / save_progress / get_progress / last_book`
  - Task 4: `MusicPlayerBar(compact=True)`
  - Task 5: `self._content_host`、`self._pre_input_host`、`chat_l`（两个弹簧）、`_scroll_to_bottom()`
  - 基类 `RoomWindow.__init__(friend_id, room_key, parent)`
- Produces（Task 7/8 依赖）:
  - `class ReadingRoomWindow(RoomWindow): __init__(self, friend_id: int, parent=None)`（room_key 固定 `"reading"`）
  - 属性：`music_bar`、`_book_path: str`（空=没书）、`_text_src: PdfTextSource | None`、`_pdf_view`、`_pdf_doc`、`_pick_book_btn/_prev_page_btn/_next_page_btn/_page_label`
  - 方法：`_page(self) -> int`（1 基当前页）、`_load_book(self, path: str) -> bool`、`_on_page_changed(self, page0: int)`、`_save_progress_now(self)`、`_check_scan_hint(self)`、`_restore_last_book(self)`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_reading_room.py`：

```python
"""沉浸式阅读室测试"""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel

from shadowtalk.data.database import Database
from shadowtalk.data.repositories import FriendRepository

Database.get_connection()

app = QApplication.instance() or QApplication(sys.argv)

BOOK = Path(r"C:\work\aiworkspace12\novels\PDF合集\西游记的正确打开方式.pdf")
needs_book = pytest.mark.skipif(not BOOK.is_file(), reason="本机无目标书")


def _make_friend(name="小读"):
    return FriendRepository.insert(name, "", "你是小读")


class _FakeWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    approval_requested = Signal(str, list, str)
    activity = Signal(str)

    def __init__(self, *a, **k):
        super().__init__()
        self.messages = k.get("messages", a[3] if len(a) > 3 else [])

    def cancel(self): pass

    def isRunning(self): return False

    def wait(self, ms): return True

    def start(self): pass


class _FakeTextSrc:
    """伪文本源：章节标题在 97 页"""
    page_count = 200
    _pages = {
        97: "第22章 签约叛将\n他说完便走了。",
        98: "次日清晨的情节。",
        99: "正午的情节。",
        100: "傍晚，说书人又开讲了。",
    }

    def page_text(self, page):
        return self._pages.get(page, f"第{page}页的普通正文。")


@pytest.fixture()
def room(monkeypatch):
    from shadowtalk.ui.widgets import room_window as rw
    from shadowtalk.ui.widgets.reading_room import ReadingRoomWindow
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = ReadingRoomWindow(fid)
    yield win
    win.close()


def test_reading_window_controls_exist(room):
    assert room._pick_book_btn is not None
    assert room._prev_page_btn is not None
    assert room._next_page_btn is not None
    assert room._page_label is not None
    assert room.music_bar._prev_btn.isHidden()    # 精简播放条：无切歌
    assert "阅读室" in room.windowTitle()


def test_no_book_label_hint(room):
    assert "还没选书" in room._page_label.text()


def test_load_book_missing_file_stays_empty(room):
    assert room._load_book(r"C:\nonexistent\书.pdf") is False
    assert room._book_path == ""
    assert "打开失败" in room._page_label.text()


def test_page_change_debounce_saves(room):
    from shadowtalk.core import reading_service as rs
    room._book_path = "D:/books/debounce.pdf"
    room._text_src = _FakeTextSrc()
    room._on_page_changed(99)
    assert room._page_label.text() == "第 100 / 200 页"
    assert room._save_timer.isActive()        # 防抖计时在跑
    room._save_progress_now()
    assert rs.get_progress(room.friend_id, "D:/books/debounce.pdf") == 100


def test_scan_hint_when_no_text(room):
    class _Empty:
        page_count = 10

        def page_text(self, page):
            return ""
    room._text_src = _Empty()
    room._page = lambda: 1
    room._check_scan_hint()
    assert "扫描件" in room._page_label.text()


@needs_book
def test_real_book_load_and_nav(room):
    assert room._load_book(str(BOOK)) is True
    assert room._text_src.page_count == 360
    room._pdf_view.pageNavigator().jump(99, QPointF(0, 0))   # → 第100页
    assert room._page() == 100
    assert room._page_label.text() == "第 100 / 360 页"


@needs_book
def test_restore_last_book(monkeypatch):
    from shadowtalk.core import reading_service as rs
    from shadowtalk.ui.widgets.reading_room import ReadingRoomWindow
    fid = _make_friend()
    rs.save_progress(fid, str(BOOK), 100)
    win = ReadingRoomWindow(fid)
    assert win._book_path == str(BOOK)
    assert win._page() == 100
    win.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_room.py -v`
Expected: FAIL（模块 `reading_room` 不存在）

- [ ] **Step 3: 写实现**

新建 `shadowtalk/ui/widgets/reading_room.py`（本任务写窗口壳；`_current_scene_prompt`/气泡部分 Task 7 再加，先不覆盖基类行为）：

```python
# shadowtalk/ui/widgets/reading_room.py
"""沉浸式阅读室：PDF 共读 + 边读边聊 + 环境音乐

复用咖啡馆 RoomWindow 骨架：书页区插入基类内容区宿主（左书右聊）。
按需阅读（设计 2026-08-17）：翻页她不读不语；发消息时才现场组装
"当前页+前几页+章节标题"进场景上下文。进度记 reading_progress 续读。
"""
import logging
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
)

from shadowtalk.core import reading_service as rs
from shadowtalk.ui.widgets.music_player_bar import MusicPlayerBar
from shadowtalk.ui.widgets.room_window import RoomWindow

logger = logging.getLogger(__name__)

_SAVE_DEBOUNCE_MS = 1000   # 停止翻页 1 秒后落库


class ReadingRoomWindow(RoomWindow):
    """阅读室：左边书页（QPdfView），右边聊天；底栏翻书 + 环境音乐"""

    def __init__(self, friend_id: int, parent=None):
        super().__init__(friend_id, "reading", parent=parent)
        self._book_path = ""
        self._text_src = None          # rs.PdfTextSource | None

        # 书页区：插到内容区宿主最左，占 3/5；聊天列仍透出背景图
        self._pdf_doc = QPdfDocument(self)
        self._pdf_view = QPdfView(self)
        self._pdf_view.setDocument(self._pdf_doc)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self._pdf_view.pageNavigator().currentPageChanged.connect(
            self._on_page_changed)
        self._content_host.insertWidget(0, self._pdf_view, 3)
        self._content_host.setStretchFactor(self.chat_scroll, 2)

        # 进度防抖落库
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_progress_now)

        self._build_book_bar()
        self._restore_last_book()

    # ── 底栏：翻书控制 + 环境音乐（精简播放条）──
    def _build_book_bar(self):
        bar = QFrame()
        bar.setStyleSheet("background-color: rgba(20,16,12,150);")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 6, 14, 6)

        def btn(text, tip, slot):
            b = QPushButton(text)
            b.setFixedSize(32, 32)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setAutoDefault(False)   # Enter 只用于发消息
            b.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,40); color: #F5EFE6;
                              border: none; border-radius: 16px; font-size: 14px; }
                QPushButton:hover { background: rgba(255,255,255,90); }
            """)
            b.clicked.connect(slot)
            return b

        self._pick_book_btn = btn("📖", "选一本 PDF 开始读", self._on_pick_book)
        self._prev_page_btn = btn("⏮", "上一页", self._prev_page)
        self._next_page_btn = btn("⏭", "下一页", self._next_page)
        self._page_label = QLabel("还没选书 —— 点 📖 打开一本 PDF")
        self._page_label.setStyleSheet(
            "color: rgba(245,239,230,220); font-size: 12px;"
            " background: transparent;")
        row.addWidget(self._pick_book_btn)
        row.addWidget(self._prev_page_btn)
        row.addWidget(self._next_page_btn)
        row.addWidget(self._page_label, 1)

        self.music_bar = MusicPlayerBar(compact=True)
        row.addWidget(self.music_bar)
        self._pre_input_host.addWidget(bar)

    # ── 书加载与翻页 ──
    def _on_pick_book(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选一本 PDF", "", "电子书 (*.pdf)")
        if path:
            self._load_book(path)

    def _load_book(self, path: str) -> bool:
        """打开书：渲染文档 + 文本源 + 续读页码；失败留在空状态"""
        self._pdf_doc.load(path)
        if self._pdf_doc.status() != QPdfDocument.Status.Ready:
            self._book_path = ""
            self._text_src = None
            self._page_label.setText("打开失败 —— 换一本试试")
            return False
        try:
            self._text_src = rs.PdfTextSource(path)
        except rs.PdfTextSourceError as e:
            self._book_path = ""
            self._text_src = None
            self._page_label.setText(f"这本书读不了：{e}")
            return False
        self._book_path = path
        page = rs.get_progress(self.friend_id, path) or 1
        page = min(page, self._text_src.page_count)
        self._pdf_view.pageNavigator().jump(page - 1, QPointF(0, 0))
        self._on_page_changed(page - 1)
        self._check_scan_hint()
        return True

    def _check_scan_hint(self):
        """打开书时对当前页提取一次：提不到字 → 扫描件提示（她读不到）"""
        if (self._text_src is not None
                and not self._text_src.page_text(self._page()).strip()):
            self._page_label.setText(
                f"扫描件：她读不到这本书的正文（第{self._page()}页无文本层）")

    def _restore_last_book(self):
        last = rs.last_book(self.friend_id)
        if last and Path(last[0]).is_file():
            self._load_book(last[0])

    def _page(self) -> int:
        """当前页（1 基）"""
        return self._pdf_view.pageNavigator().currentPage() + 1

    def _on_page_changed(self, page0: int):
        if self._text_src:
            self._page_label.setText(
                f"第 {page0 + 1} / {self._text_src.page_count} 页")
        if self._book_path:
            self._save_timer.start()

    def _prev_page(self):
        p = self._page() - 1
        if p >= 1:
            self._pdf_view.pageNavigator().jump(p - 1, QPointF(0, 0))

    def _next_page(self):
        if self._text_src and self._page() < self._text_src.page_count:
            self._pdf_view.pageNavigator().jump(self._page(), QPointF(0, 0))

    def _save_progress_now(self):
        if self._book_path and self._text_src:
            rs.save_progress(self.friend_id, self._book_path, self._page())

    def closeEvent(self, event):
        self._save_progress_now()
        self.music_bar.stop()
        super().closeEvent(event)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_room.py -v`
Expected: 7 PASS（无书机器上 2 SKIP + 5 PASS）

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/ui/widgets/reading_room.py tests/test_reading_room.py
git commit -m "feat: reading room window shell (pdf view, nav, resume, debounce)"
```

---

### Task 7: 按需上下文 + 流式对话（阅读室的"她"）

**Files:**
- Modify: `shadowtalk/ui/widgets/reading_room.py`（追加三个覆盖方法）
- Test: `tests/test_reading_room.py`（追加）

**Interfaces:**
- Consumes:
  - Task 1: `find_chapter_title / build_window_text`（传 `self._text_src.page_text`）
  - 基类 `RoomBubble(text, role, msg_id, icon)`、`_on_play`、`chat_l`（`[上弹簧, ..., 下弹簧]`）、`_scroll_to_bottom()`、钩子 `_show_user_message`（Task 5）
- Produces（Task 8 无新依赖，这是行为完成态）:
  - `_current_scene_prompt(self) -> str`：基类场景（rooms 表的阅读室人设）+ 书名/页码/章节标题/滑动窗口正文
  - `_show_ai_reply(self, text, msg_id=0)`：流式追加（不替换旧气泡）
  - `_show_user_message(self, text)`：用户气泡流式追加

- [ ] **Step 1: 写失败测试**

在 `tests/test_reading_room.py` 末尾追加：

```python
# ── 按需上下文 + 流式对话（Task 7）──

def test_scene_prompt_without_book(room):
    scene = room._current_scene_prompt()
    assert "阅读室" in scene
    assert "不是咖啡馆" in scene
    assert "还没开始读书" in scene


def test_scene_prompt_lazy_window(room):
    """发问时才组装：书名/页码/章节标题/前几页正文一次到位"""
    room._book_path = r"D:/books/测试小说.pdf"
    room._text_src = _FakeTextSrc()
    room._page = lambda: 100
    scene = room._current_scene_prompt()
    assert "测试小说" in scene
    assert "第 100 页" in scene
    assert "第22章 签约叛将" in scene
    assert "傍晚，说书人又开讲了。" in scene      # 当前页正文
    assert "次日清晨的情节。" in scene            # 前几页正文
    assert "第96~100页" in scene
    # 场景只谈书，不掺音乐（环境音乐是背景）
    assert "正在播放" not in scene


def test_scene_prompt_scan_book(room):
    class _Empty:
        page_count = 10

        def page_text(self, page):
            return ""
    room._book_path = "D:/books/scan.pdf"
    room._text_src = _Empty()
    room._page = lambda: 3
    scene = room._current_scene_prompt()
    assert "扫描件" in scene


def test_chat_bubbles_flow(room):
    """讨论双方的话都在右列流式排列（可回看），不再只显示她最新一条"""
    from shadowtalk.ui.widgets.room_window import RoomBubble
    room.input_edit.setText("这段什么意思？")
    room._on_send()
    texts = [l.text() for l in room.chat_host.findChildren(QLabel)]
    assert any("这段什么意思？" in t for t in texts)
    room._show_ai_reply("意思是…", 1)
    bubbles = room.chat_host.findChildren(RoomBubble)
    assert len(bubbles) == 2                    # 用户 + 她各一条
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_room.py -v`
Expected: 新增 4 个 FAIL；Task 6 的 7 个仍 PASS

- [ ] **Step 3: 写实现**

在 `ReadingRoomWindow` 类中（`closeEvent` 之前）追加：

```python
    # ── 按需阅读：发问时才组装她的视野（翻页不读不语）──
    def _current_scene_prompt(self) -> str:
        base = super()._current_scene_prompt()
        if not self._text_src:
            return base + "\n（还没开始读书，只有你们两个人在阅读室里。）"
        page = self._page()
        parts = [f"\n正在一起读《{Path(self._book_path).stem}》"
                 f"（共{self._text_src.page_count}页），用户刚翻到第 {page} 页。"]
        chapter = rs.find_chapter_title(self._text_src.page_text, page)
        if chapter:
            parts.append(f"所在章节：{chapter}。")
        window_text = rs.build_window_text(
            self._text_src.page_text, page, self._text_src.page_count)
        if window_text:
            parts.append(
                f"【用户当前读到的正文（第{max(1, page - 4)}~{page}页）】\n"
                f"{window_text}")
        else:
            parts.append("这本书提不出文本（扫描件），你还没读到内容——"
                         "被问到剧情时如实说明。")
        return base + "\n".join(parts)

    # ── 流式对话：右列正常排列可回看（不同于咖啡馆"只显示最新一条"）──
    def _show_user_message(self, text: str):
        self._append_bubble(RoomBubble(text, "user"))

    def _show_ai_reply(self, text: str, msg_id: int = 0):
        bubble = RoomBubble(text, "ai", msg_id, icon="📖")
        bubble.play_requested.connect(self._on_play)
        self._append_bubble(bubble)
        self._ai_bubble = bubble

    def _append_bubble(self, bubble):
        # 插到下弹簧之前：消息从上往下流式排列，超出滚动
        self.chat_l.insertWidget(self.chat_l.count() - 1, bubble)
        self._scroll_to_bottom()
```

同时把文件顶部导入改为：

```python
from shadowtalk.ui.widgets.room_window import RoomBubble, RoomWindow
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_room.py -v`
Expected: 11 PASS（无书机器 2 SKIP + 9 PASS）

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/ui/widgets/reading_room.py tests/test_reading_room.py
git commit -m "feat: reading room lazy scene context and flowing chat"
```

---

### Task 8: 主界面入口 + 全量回归

**Files:**
- Modify: `shadowtalk/ui/main_window.py:228-266`（`_on_open_room`）
- Test: 全量 `python -m pytest tests/ -v`

**Interfaces:**
- Consumes: Task 6/7 的 `ReadingRoomWindow(friend_id, parent=self)`；现有房间入口模式（选房间 → 选好友 → 开窗口）
- Produces: 用户可从"房间"按钮进入阅读室

- [ ] **Step 1: 改入口**

`shadowtalk/ui/main_window.py` 的 `_on_open_room` 三处：

房间列表（约 235-237 行）：

```python
        room_key, ok = QInputDialog.getItem(
            self, "选择房间", "去哪个房间？",
            ["☕ 咖啡馆", "🎵 音乐室", "📖 阅读室"], 0, False)
```

key_map（约 240-241 行）：

```python
        key_map = {"☕ 咖啡馆": ("cafe", "请谁去喝咖啡？"),
                   "🎵 音乐室": ("music", "请谁一起听歌？"),
                   "📖 阅读室": ("reading", "请谁一起读书？")}
```

开窗分支（约 259-263 行）：

```python
        if room_key_id == "music":
            from shadowtalk.ui.widgets.music_room import MusicRoomWindow
            room = MusicRoomWindow(friend_id, parent=self)
        elif room_key_id == "reading":
            from shadowtalk.ui.widgets.reading_room import ReadingRoomWindow
            room = ReadingRoomWindow(friend_id, parent=self)
        else:
            room = RoomWindow(friend_id, "cafe", parent=self)
```

- [ ] **Step 2: 全量测试回归**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS（阅读室相关含少量 SKIP 时为正常——本机无目标书才 SKIP）

- [ ] **Step 3: 手工冒烟（真实环境验证）**

Run: `python -m shadowtalk.main`（在 `c:\work\aiworkspace18` 下）
操作路径与预期：
1. 侧边栏"☕ 房间"→ 选 "📖 阅读室" → 选任一好友 → 窗口标题含"阅读室"
2. 底栏点 📖 → 选 `C:\work\aiworkspace12\novels\PDF合集\西游记的正确打开方式.pdf` → 页码显示"第 1 / 360 页"
3. ⏭ 翻几页 → 页码跟走；等 1 秒后关窗重进 → 自动回到最后翻的页
4. 输入"这页讲了什么？"发送 → 她的回答贴合当前页剧情（非泛泛而谈）
5. 底栏 🎵 选几首轻音乐 → 自动连播；她开口说话时音乐自动压低
6. 换背景按钮仍可用；离开房间后主界面聊天区正常刷新

- [ ] **Step 4: Commit**

```bash
git add shadowtalk/ui/main_window.py
git commit -m "feat: reading room entry in room picker"
```
