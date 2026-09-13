# TTS 语音播报实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ShadowTalk 聊天界面中 AI 回复可语音朗读：气泡喇叭按钮手动点播 + 设置里可选的自动朗读 + 每好友独立音色。

**Architecture:** core 层纯 Python 封装 edge-tts 合成与缓存（零 Qt 依赖，可单测）；ui 层 TtsWorker（QThread）后台合成、TtsPlayer（QMediaPlayer 单例）播放，同时只服务一条、新播放打断旧的；音色解析为 好友指定 > 全局默认 > 兜底。缓存 `data/tts_cache/{msg_id}.mp3`，按消息 ID 命中即不重复合成。

**Tech Stack:** Python 3.11、PySide6 6.11（QtMultimedia）、edge-tts>=6.1.0、pytest（含 Qt 控件测试先例，QApplication 实例化）

## Global Constraints

- core/ 禁止 import PySide6（`tts_service.py` 必须纯 Python）
- UI 线程禁止执行网络合成（edge-tts 调用只能在工作线程）
- 同时只服务一条语音；新 `play()` 打断旧的（播放器与合成任务均只保留最新引用，旧任务结果按 msg_id 失配丢弃，仿照 AIWorker 的 stale 守卫模式）
- 缓存键 = 消息 ID，`cache_path(msg_id)` = `<cwd>/data/tts_cache/{msg_id}.mp3`；msg_id 为 0/None 时不缓存、合成到临时文件直接播
- 失败只提示不崩溃、不弹阻塞对话框；缓存目录不可写降级为"合成后不落盘直接播放"
- 空文本/纯空白点播直接忽略
- 音色清单唯一来源：`tts_service.TTS_VOICES`（下拉框与校验共用）
- 测试命令统一 `python -m pytest <path> -v`（项目默认 python 为 3.11）

---

### Task 1: core 层 TTS 服务（合成 + 缓存 + 音色解析）

**Files:**
- Create: `shadowtalk/core/tts_service.py`
- Create: `tests/test_tts_service.py`
- Modify: `requirements.txt`（追加 `edge-tts>=6.1.0`）

**Interfaces:**
- Produces:
  - `TTS_VOICES: list[dict]` — 每项 `{"label": str, "voice": str}`，共 8 个（中文 6 + 英文 2）
  - `DEFAULT_VOICE: str` = `"zh-CN-XiaoxiaoNeural"`
  - `VOICE_IDS: set[str]`
  - `resolve_voice(friend_voice: str, global_voice: str) -> str`
  - `cache_dir() -> Path`（不存在则创建，含父目录）
  - `cache_path(msg_id: int) -> Path`
  - `remove_cached(msg_id: int) -> None`（文件不存在时静默）
  - `synthesize(text: str, voice: str, out_path) -> None`（空文本直接返回；edge_tts 惰性导入）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tts_service.py
import sys
from pathlib import Path

import pytest

from shadowtalk.core import tts_service
from shadowtalk.core.tts_service import (
    DEFAULT_VOICE, TTS_VOICES, VOICE_IDS,
    cache_dir, cache_path, remove_cached, resolve_voice, synthesize,
)


def test_voice_list_contains_default():
    assert DEFAULT_VOICE in VOICE_IDS
    assert len(TTS_VOICES) >= 8
    for v in TTS_VOICES:
        assert set(v) == {"label", "voice"}
        assert v["voice"] in VOICE_IDS


def test_resolve_voice_friend_wins():
    assert resolve_voice("zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural") == "zh-CN-YunxiNeural"


def test_resolve_voice_global_fallback():
    # 好友音色非法 → 用全局
    assert resolve_voice("no-such-voice", "zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"
    # 好友为空 → 用全局
    assert resolve_voice("", "zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"


def test_resolve_voice_default_fallback():
    assert resolve_voice("bad", "worse") == DEFAULT_VOICE


def test_cache_path_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "_BASE_DIR", tmp_path)
    assert cache_path(42) == tmp_path / "data" / "tts_cache" / "42.mp3"


def test_cache_dir_creates(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "_BASE_DIR", tmp_path)
    d = cache_dir()
    assert d.is_dir()


def test_remove_cached_quiet_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_service, "_BASE_DIR", tmp_path)
    remove_cached(999)  # 不抛异常


def test_synthesize_empty_text_no_call(tmp_path, monkeypatch):
    called = []
    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text, self.voice = text, voice
        def save_sync(self, path):
            called.append((self.text, self.voice, path))
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    synthesize("   ", "zh-CN-XiaoxiaoNeural", tmp_path / "x.mp3")
    assert called == []


def test_synthesize_calls_edge_tts(tmp_path, monkeypatch):
    seen = {}
    class FakeCommunicate:
        def __init__(self, text, voice):
            seen["text"], seen["voice"] = text, voice
        def save_sync(self, path):
            seen["path"] = path
            Path(path).write_bytes(b"mp3")
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    out = tmp_path / "out.mp3"
    synthesize("你好", "zh-CN-XiaoxiaoNeural", out)
    assert seen == {"text": "你好", "voice": "zh-CN-XiaoxiaoNeural", "path": str(out)}
    assert out.read_bytes() == b"mp3"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_tts_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'shadowtalk.core.tts_service'`）

- [ ] **Step 3: 实现 tts_service.py**

```python
# shadowtalk/core/tts_service.py
"""
TTS 语音合成服务（纯 Python，禁止 import PySide6）

职责：音色清单、音色解析、edge-tts 合成、本地音频缓存。
播放（QtMultimedia）在 ui 层，见 ui/widgets/tts_player.py。
"""
from pathlib import Path

# 开发时 cwd()，打包后 exe 所在目录 —— 与 config.paths.get_base_dir() 一致
import sys
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path.cwd()

TTS_VOICES = [
    {"label": "晓晓（女·温柔）", "voice": "zh-CN-XiaoxiaoNeural"},
    {"label": "云希（男·阳光）", "voice": "zh-CN-YunxiNeural"},
    {"label": "晓伊（女·活泼）", "voice": "zh-CN-XiaoyiNeural"},
    {"label": "云扬（男·新闻）", "voice": "zh-CN-YunyangNeural"},
    {"label": "晓辰（女·青春）", "voice": "zh-CN-XiaochenNeural"},
    {"label": "云健（男·沉稳）", "voice": "zh-CN-YunjianNeural"},
    {"label": "Aria（英·女）", "voice": "en-US-AriaNeural"},
    {"label": "Guy（英·男）", "voice": "en-US-GuyNeural"},
]

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_IDS = {v["voice"] for v in TTS_VOICES}


def resolve_voice(friend_voice: str, global_voice: str) -> str:
    """音色解析：好友指定 > 全局默认 > 兜底"""
    if friend_voice in VOICE_IDS:
        return friend_voice
    if global_voice in VOICE_IDS:
        return global_voice
    return DEFAULT_VOICE


def cache_dir() -> Path:
    """缓存目录，不存在则创建（含父目录）"""
    d = _BASE_DIR / "data" / "tts_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(msg_id: int) -> Path:
    return _BASE_DIR / "data" / "tts_cache" / f"{msg_id}.mp3"


def remove_cached(msg_id: int) -> None:
    """删除缓存文件（播放失败清损坏缓存用），不存在时静默"""
    try:
        cache_path(msg_id).unlink(missing_ok=True)
    except OSError:
        pass


def synthesize(text: str, voice: str, out_path) -> None:
    """将文本合成为 MP3 写入 out_path。空文本直接返回。

    edge_tts 惰性导入：即使包缺失，import 本模块也不失败，
    仅在真正合成时抛 ImportError（由 ui 层统一提示失败）。
    """
    if not text or not text.strip():
        return
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    communicate.save_sync(str(out_path))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_tts_service.py -v`
Expected: PASS（10 个测试）

- [ ] **Step 5: 安装依赖 + 提交**

```bash
python -m pip install "edge-tts>=6.1.0"
git add shadowtalk/core/tts_service.py tests/test_tts_service.py requirements.txt
git commit -m "feat: add core TTS service (synthesis, cache, voice resolution)"
```

---

### Task 2: 配置键、friends 表迁移、数据层

**Files:**
- Modify: `shadowtalk/config/settings.py:8-20`（DEFAULTS 加两键）
- Modify: `shadowtalk/data/database.py:85-94`（_migrate 加 voice 列）
- Modify: `shadowtalk/models/entities.py:5-11`（Friend 加 voice 字段）
- Modify: `shadowtalk/data/repositories.py:6-12`（MessageRepository.insert 返回 lastrowid）
- Modify: `shadowtalk/data/repositories.py:117-125`（FriendRepository.insert 加 voice 参数）
- Modify: `shadowtalk/data/repositories.py:142-153`（FriendRepository.update allowed 加 voice）
- Test: `tests/test_settings.py`、`tests/test_database.py`、`tests/test_repositories.py`

**Interfaces:**
- Consumes: `tts_service.DEFAULT_VOICE`
- Produces:
  - `Settings.get("tts_voice")` 默认 `zh-CN-XiaoxiaoNeural`；`Settings.get("tts_auto_play")` 默认 `"0"`
  - `FriendRepository.insert(..., voice="")`；`FriendRepository.update(..., voice=...)`
  - `MessageRepository.insert(...) -> int`（lastrowid）
  - `Friend` 数据类含 `voice: str = ""`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_settings.py 追加
def test_tts_defaults():
    Settings.init_defaults()
    assert Settings.get("tts_voice") == "zh-CN-XiaoxiaoNeural"
    assert Settings.get("tts_auto_play") == "0"
```

```python
# tests/test_database.py 追加（沿用文件顶部 OLD_FRIENDS_SCHEMA 模式）
OLD_FRIENDS_SCHEMA_NO_VOICE = """
CREATE TABLE friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    ai_role TEXT DEFAULT '',
    user_role TEXT DEFAULT '',
    work_dir TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

def test_migrate_adds_voice_column(monkeypatch):
    # 用旧 schema 建表后打开连接，迁移应补上 voice 列
    import sqlite3, tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.executescript(OLD_FRIENDS_SCHEMA_NO_VOICE)
        conn.close()
        import shadowtalk.data.database as db_module
        monkeypatch.setattr(db_module, "DB_PATH", path)
        Database._conn = None
        db_conn = Database.get_connection()
        cols = {row[1] for row in db_conn.execute("PRAGMA table_info(friends)")}
        assert "voice" in cols
        Database.close()
    finally:
        for suffix in ["", "-wal", "-shm"]:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
```

```python
# tests/test_repositories.py 追加
def test_friend_insert_and_update_voice():
    fid = FriendRepository.insert(
        name="测试好友", remark="", system_prompt="",
        voice="zh-CN-YunxiNeural"
    )
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-YunxiNeural"
    FriendRepository.update(fid, voice="zh-CN-XiaoyiNeural")
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-XiaoyiNeural"

def test_message_insert_returns_id():
    fid = FriendRepository.insert(name="m", remark="", system_prompt="")
    mid = MessageRepository.insert(fid, "ai", "你好", 1)
    assert isinstance(mid, int) and mid > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_settings.py tests/test_database.py tests/test_repositories.py -v`
Expected: FAIL（`test_tts_defaults` 断言失败 / `friend_insert_and_update_voice` 键错误 `voice` / `test_migrate_adds_voice_column` 断言失败 / `message_insert_returns_id` 返回 None）

- [ ] **Step 3: 实现**

settings.py DEFAULTS 追加两行（在 `"max_output_tokens": "2000",` 之后）：

```python
        "tts_voice": "zh-CN-XiaoxiaoNeural",
        "tts_auto_play": "0",
```

database.py `_migrate` 末尾追加：

```python
        if "voice" not in existing:
            conn.execute("ALTER TABLE friends ADD COLUMN voice TEXT DEFAULT ''")
```

entities.py Friend 数据类追加字段：

```python
    voice: str = ""
```

repositories.py：

```python
    # MessageRepository.insert 末尾加 return cursor.lastrowid
    @staticmethod
    def insert(friend_id, sender_type, content, round_index):
        with Database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
                "VALUES (?, ?, ?, ?)",
                (friend_id, sender_type, content, round_index)
            )
            return cursor.lastrowid

    # FriendRepository.insert 加 voice 参数（默认 ""），SQL 与参数同步加一列
    @staticmethod
    def insert(name, remark, system_prompt, avatar_path="",
               ai_role="", user_role="", work_dir="", voice=""):
        with Database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO friends (name, remark, system_prompt, avatar_path, ai_role, user_role, work_dir, voice) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, remark, system_prompt, avatar_path, ai_role, user_role, work_dir, voice)
            )
            return cursor.lastrowid

    # FriendRepository.update allowed 集合加 "voice"
        allowed = {"name", "remark", "system_prompt", "avatar_path", "ai_role", "user_role", "work_dir", "voice"}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_settings.py tests/test_database.py tests/test_repositories.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/config/settings.py shadowtalk/data/database.py shadowtalk/models/entities.py shadowtalk/data/repositories.py tests/test_settings.py tests/test_database.py tests/test_repositories.py
git commit -m "feat: add tts settings keys, friends.voice migration, repository voice support"
```

---

### Task 3: 合成工作线程与播放器（Qt 层）

**Files:**
- Create: `shadowtalk/ui/threads/tts_worker.py`
- Create: `shadowtalk/ui/widgets/tts_player.py`
- Test: `tests/test_tts_player.py`

**Interfaces:**
- Consumes: `tts_service.synthesize`、`tts_service.cache_path`、`tts_service.cache_dir`、`tts_service.remove_cached`
- Produces:
  - `TtsWorker(QThread)`：`succeeded = Signal(str, int)` (mp3_path, msg_id)、`failed = Signal(int, str)` (msg_id, error)；`__init__(text, voice, msg_id, out_path)`
  - `TtsPlayer(QObject)` 信号：`playback_started = Signal(int)`、`playback_finished = Signal(int)`、`playback_failed = Signal(int)`、`synthesis_failed = Signal(int)`；方法 `play(text, voice, msg_id)`、`stop()`；懒加载单例 `get_player()`（模块级直接构造 QMediaPlayer 会在 QApplication 缺失时失败，见 Step 4 说明）
  - 播放语义：新 play 打断旧的（worker 结果按 msg_id 失配丢弃）；msg_id 为 0/None 或缓存不可写 → 合成到临时文件直接播

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tts_player.py
"""TtsPlayer 状态机测试：不触网、不发声、不写真实缓存，TtsWorker 用桩替换"""
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from shadowtalk.ui.widgets import tts_player as tts_player_module
from shadowtalk.ui.widgets.tts_player import TtsPlayer


class FakeWorker(QObject):
    """桩：start() 不发信号；由测试手动 emit_success() 模拟结果到达"""
    succeeded = Signal(str, int)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, text, voice, msg_id, out_path):
        super().__init__()
        self._msg_id = msg_id
        self.out_path = Path(out_path)

    def start(self):
        pass

    def emit_success(self):
        self.out_path.write_bytes(b"mp3")
        self.succeeded.emit(str(self.out_path), self._msg_id)


class FailingWorker(QObject):
    succeeded = Signal(str, int)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, text, voice, msg_id, out_path):
        super().__init__()
        self._msg_id = msg_id

    def start(self):
        self.failed.emit(self._msg_id, "network down")


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """隔离：worker 桩 + 临时缓存路径 + 不碰真实音频设备"""
    monkeypatch.setattr(tts_player_module, "TtsWorker", FakeWorker)
    monkeypatch.setattr(tts_player_module, "cache_path",
                        lambda mid: tmp_path / f"{mid}.mp3")
    monkeypatch.setattr(tts_player_module, "cache_dir",
                        lambda: tmp_path / "tts_cache")
    monkeypatch.setattr(tts_player_module, "_TEMP_DIR", str(tmp_path))
    # 记录"开始播放"调用，替代真实音频
    started = []

    def fake_start(path, mid):
        started.append(mid)

    return tmp_path, started, fake_start


def make_player(fake_start):
    p = TtsPlayer()
    p._start_media = fake_start
    return p


def test_play_empty_text_noop(isolated):
    tmp_path, started, fake_start = isolated
    p = make_player(fake_start)
    p.play("   ", "zh-CN-XiaoxiaoNeural", 1)
    assert started == []
    assert p._worker is None


def test_worker_failure_emits_synthesis_failed(isolated, monkeypatch, tmp_path):
    tmp_path, started, fake_start = isolated
    monkeypatch.setattr(tts_player_module, "TtsWorker", FailingWorker)
    p = make_player(fake_start)
    failed = []
    p.synthesis_failed.connect(lambda mid: failed.append(mid))
    p.play("你好", "zh-CN-XiaoxiaoNeural", 7)
    assert failed == [7]
    # 状态复位：再次请求不被旧 msg_id 卡住
    p.play("你好", "zh-CN-XiaoxiaoNeural", 8)
    assert failed == [7, 8]


def test_stale_worker_result_ignored(isolated):
    """msg_id 失配的合成结果必须丢弃（打断语义）"""
    tmp_path, started, fake_start = isolated
    p = make_player(fake_start)
    p.play("旧消息", "zh-CN-XiaoxiaoNeural", 1)
    old_worker = p._worker
    p.play("新消息", "zh-CN-XiaoxiaoNeural", 2)  # 打断：替换 worker、更新 msg_id
    old_worker.emit_success()  # 旧 worker 结果此刻才到 → 应被丢弃
    assert started == []
    assert p._current_msg_id == 2
    # 正向对照：新 worker 结果正常播放
    p._worker.emit_success()
    assert started == [2]


def test_cache_hit_skips_worker(isolated):
    tmp_path, started, fake_start = isolated
    (tmp_path / "3.mp3").write_bytes(b"mp3")  # 预置缓存命中
    p = make_player(fake_start)
    p.play("你好", "zh-CN-XiaoxiaoNeural", 3)
    assert started == [3]
    assert p._worker is None  # 未新建合成线程


def test_retired_worker_retained_until_finished(isolated):
    """打断后旧 worker 必须被保留（防"QThread: Destroyed while thread is still running"），
    finished 后从保留列表移除"""
    tmp_path, started, fake_start = isolated
    p = make_player(fake_start)
    p.play("一", "zh-CN-XiaoxiaoNeural", 1)
    first = p._worker
    p.play("二", "zh-CN-XiaoxiaoNeural", 2)  # 打断：第一个 worker 应进入保留列表
    assert first in p._retired
    assert p._worker is not first
    first.emit_success()  # stale 结果仍被丢弃
    assert started == []
    first.finished.emit()  # 线程结束 → 从保留列表移除
    assert first not in p._retired
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_tts_player.py -v`
Expected: FAIL（`ModuleNotFoundError: shadowtalk.ui.threads.tts_worker`）

- [ ] **Step 3: 实现 tts_worker.py**

```python
# shadowtalk/ui/threads/tts_worker.py
"""TTS 合成工作线程：edge-tts 网络合成不阻塞 UI"""
import logging
from PySide6.QtCore import QThread, Signal

from shadowtalk.core.tts_service import synthesize


logger = logging.getLogger(__name__)


class TtsWorker(QThread):
    succeeded = Signal(str, int)   # (mp3_path, msg_id)
    failed = Signal(int, str)      # (msg_id, error)

    def __init__(self, text: str, voice: str, msg_id: int, out_path):
        super().__init__()
        self._text = text
        self._voice = voice
        self._msg_id = msg_id
        self._out_path = out_path

    def run(self):
        try:
            synthesize(self._text, self._voice, self._out_path)
            self.succeeded.emit(str(self._out_path), self._msg_id)
        except Exception as e:
            logger.error("TTS 合成失败: msg_id=%s 错误=%s", self._msg_id, e)
            self.failed.emit(self._msg_id, str(e))
```

- [ ] **Step 4: 实现 tts_player.py**

```python
# shadowtalk/ui/widgets/tts_player.py
"""
TTS 播放器：QMediaPlayer 单例，同时只服务一条语音。
新 play() 打断旧的（旧合成线程结果按 msg_id 失配丢弃）。
"""
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from shadowtalk.core.tts_service import cache_dir, cache_path, remove_cached
from shadowtalk.ui.threads.tts_worker import TtsWorker


logger = logging.getLogger(__name__)
_TEMP_DIR = tempfile.gettempdir()


class TtsPlayer(QObject):
    playback_started = Signal(int)    # msg_id
    playback_finished = Signal(int)   # msg_id
    playback_failed = Signal(int)     # msg_id
    synthesis_failed = Signal(int)    # msg_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_media_error)
        self._worker = None      # 当前合成线程（只保留最新）
        self._retired = []       # 在途旧 worker 保留列表（防 QThread 运行中销毁）
        self._current_msg_id = None
        self._cache_ok = True

    # ── 对外接口 ──
    def play(self, text: str, voice: str, msg_id: int):
        """播放文本。空文本忽略；打断当前播放/合成。"""
        if not text or not text.strip():
            return
        self.stop()
        self._current_msg_id = msg_id
        if msg_id and cache_path(msg_id).exists():
            self._start_media(str(cache_path(msg_id)), msg_id)
            return
        # 需要合成：msg_id 有效且缓存可写 → 缓存路径；否则临时文件（不缓存）
        if msg_id:
            try:
                out_path = cache_dir() / f"{msg_id}.mp3"
                out_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._cache_ok = False
                out_path = Path(_TEMP_DIR) / f"shadowtalk_{msg_id}.mp3"
        else:
            out_path = Path(_TEMP_DIR) / f"shadowtalk_{abs(id(self))}.mp3"
        self._worker = TtsWorker(text, voice, msg_id, out_path)
        self._worker.succeeded.connect(self._on_worker_succeeded)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def stop(self):
        """停止播放并丢弃当前合成任务的结果"""
        self._stop_media()
        self._retire_worker()
        self._current_msg_id = None

    def _retire_worker(self):
        """当前 worker 转入保留列表：旧线程可能仍在合成（网络调用），
        直接释放引用会被 CPython 立即 GC，导致运行中的 QThread 被销毁
        （"QThread: Destroyed while thread is still running"，Windows 下可崩溃）。
        保留至 finished 信号后由 _on_worker_finished 移除。"""
        if self._worker is not None:
            self._retired.append(self._worker)
            self._worker = None

    def _on_worker_finished(self):
        """线程结束 → 从保留列表移除，允许安全析构"""
        w = self.sender()
        if w in self._retired:
            self._retired.remove(w)

    # ── 内部：音频 ──
    def _start_media(self, path: str, msg_id: int):
        self._player.setSource(Path(path).as_uri() if path else "")
        self._player.play()
        self._current_msg_id = msg_id
        self.playback_started.emit(msg_id)

    def _stop_media(self):
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        self._player.setSource("")

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            mid = self._current_msg_id
            self._current_msg_id = None
            self.playback_finished.emit(mid)

    def _on_media_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        mid = self._current_msg_id
        self._current_msg_id = None
        logger.error("TTS 播放失败: msg_id=%s 错误=%s", mid, error_string)
        if mid:
            remove_cached(mid)  # 清损坏缓存，下次重播重新合成
        self.playback_failed.emit(mid)

    # ── 内部：合成线程结果 ──
    def _on_worker_succeeded(self, path: str, msg_id: int):
        if msg_id != self._current_msg_id:
            return  # stale：已被更新的播放请求打断
        self._start_media(path, msg_id)

    def _on_worker_failed(self, msg_id: int, error: str):
        if msg_id != self._current_msg_id:
            return  # stale
        self._current_msg_id = None
        self.synthesis_failed.emit(msg_id)


_player_instance = None


def get_player() -> TtsPlayer:
    """懒加载单例：QMediaPlayer 构造推迟到首次使用。

    注意：main.py / test_main_window.py 在创建 QApplication 之前就
    import MainWindow（模块级），若在模块级直接构造 QMediaPlayer/
    QAudioOutput 会因 QApplication 缺失而初始化失败。首次调用时
    QApplication 必然已存在（ChatArea 只在 app 创建后实例化）。
    """
    global _player_instance
    if _player_instance is None:
        _player_instance = TtsPlayer()
    return _player_instance
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_tts_player.py -v`
Expected: PASS（4 个测试）

- [ ] **Step 6: 提交**

```bash
git add shadowtalk/ui/threads/tts_worker.py shadowtalk/ui/widgets/tts_player.py tests/test_tts_player.py
git commit -m "feat: add TTS worker thread and QMediaPlayer playback singleton"
```

---

### Task 4: 气泡喇叭按钮、ChatArea 接线、自动朗读

**Files:**
- Modify: `shadowtalk/ui/widgets/message_bubble.py:187-240`（MessageBubble：msg_id 参数、AI 角色喇叭按钮、set_playing、play_requested 信号）
- Modify: `shadowtalk/ui/widgets/chat_area.py:286-305`（add_message 加 msg_id 参数 + 信号连接）、`chat_area.py:362-371`（clear_messages 停止播放）、新增 `_on_play_requested` / `auto_play_ai_reply` / `_on_player_*` 槽
- Modify: `shadowtalk/ui/main_window.py`（add_message 调用传 msg_id；自动朗读触发；status_message → 状态栏）
- Test: `tests/test_chat_area.py`（追加）

**Interfaces:**
- Consumes: `TtsPlayer.get_player()`（懒加载单例）、`resolve_voice`、`Settings.get("tts_voice")`、`Settings.get("tts_auto_play")`、`MessageRepository.insert -> int`
- Produces:
  - `MessageBubble(text, role, timestamp, avatar_name, avatar_path, avatar_variant, msg_id=0)`；`play_requested = Signal(str, int)`；`msg_id` 属性；`set_playing(bool)`
  - `ChatArea.add_message(text, role, timestamp, msg_id=0)`；`ChatArea.auto_play_ai_reply(text, msg_id)`；`ChatArea.status_message = Signal(str)`；`set_friend_info(..., voice="")`
  - `MainWindow`：切换好友停止播放；AI 回复渲染后 `if Settings.get("tts_auto_play") == "1"` 自动朗读

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chat_area.py 追加
class StubPlayer:
    """播放器桩：记录 play/stop 调用，避免测试触发真实 edge-tts 网络合成"""
    def __init__(self):
        self.played = []
        self.stopped = 0

    def play(self, text, voice, msg_id):
        self.played.append((text, voice, msg_id))

    def stop(self):
        self.stopped += 1


def test_ai_bubble_has_play_button_and_emits_signal():
    area = ChatArea()
    area.set_friend_info(1, "小影")
    stub = StubPlayer()
    area._player = stub  # 替换真实播放器（懒加载单例），杜绝真实网络合成
    area.add_message("你好呀", "ai", "12:00", msg_id=5)
    item = area.message_list.item(0)
    bubble = area.message_list.itemWidget(item)
    # MessageBubble 内部暴露 _play_btn（AI 角色才有）
    assert bubble._play_btn is not None
    assert bubble.msg_id == 5
    got = []
    bubble.play_requested.connect(lambda text, mid: got.append((text, mid)))
    bubble._play_btn.click()
    assert got == [("你好呀", 5)]
    # 接线已连到播放器：未配好友音色 → 解析为全局默认
    assert stub.played == [("你好呀", "zh-CN-XiaoxiaoNeural", 5)]


def test_play_button_click_while_playing_requests_stop():
    """播放中（按钮 checked）再点击 → stop_requested，停止播放（规格 5.2）"""
    area = ChatArea()
    stub = StubPlayer()
    area._player = stub
    area.add_message("回复", "ai", "12:00", msg_id=2)
    bubble = area.message_list.itemWidget(area.message_list.item(0))
    stopped = []
    bubble.stop_requested.connect(lambda mid: stopped.append(mid))
    bubble.set_playing(True)   # 模拟播放中
    bubble._play_btn.click()   # checked 状态点击 → 停止请求
    assert stopped == [2]
    assert not bubble._play_btn.isChecked()
    assert stub.stopped == 1


def test_user_bubble_has_no_play_button():
    area = ChatArea()
    area.add_message("我在问", "user", "12:00", msg_id=1)
    bubble = area.message_list.itemWidget(area.message_list.item(0))
    assert bubble._play_btn is None


def test_add_message_msg_id_default_zero():
    area = ChatArea()
    area.add_message("回复", "ai", "12:00")
    bubble = area.message_list.itemWidget(area.message_list.item(0))
    assert bubble.msg_id == 0


def test_play_button_playing_state_toggle():
    area = ChatArea()
    area.add_message("回复", "ai", "12:00", msg_id=2)
    bubble = area.message_list.itemWidget(area.message_list.item(0))
    bubble.set_playing(True)
    assert bubble._play_btn.isChecked()
    bubble.set_playing(False)
    assert not bubble._play_btn.isChecked()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_chat_area.py -v`
Expected: FAIL（`AttributeError: 'MessageBubble' object has no attribute '_play_btn'`）

- [ ] **Step 3: 实现 message_bubble.py**

MessageBubble 改造（在类内）——信号声明与 __init__ 签名：

```python
class MessageBubble(QWidget):
    """完整的消息行：头像 + 气泡 + 元信息 + （AI）语音播放按钮"""

    play_requested = Signal(str, int)  # (text, msg_id)
    stop_requested = Signal(int)       # msg_id（播放中再点按钮 → 停止，规格 5.2）

    def __init__(self, text: str, role: str, timestamp: str,
                 avatar_name: str = "", avatar_path: str = "",
                 avatar_variant: str = "default", msg_id: int = 0,
                 parent=None):
        super().__init__(parent)
        self._role = role
        self.msg_id = msg_id
        self._play_btn = None
        self._build_ui(text, role, timestamp, avatar_name, avatar_path, avatar_variant)
```

_build_ui 中时间戳元信息块（原 219-229 行）替换为：

```python
        # 元信息行：AI 消息在时间戳左侧加语音播放按钮
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(0, 0, 0, 0)
        if role == "ai" and text.strip():
            self._play_btn = QPushButton("🔊")
            self._play_btn.setFixedSize(22, 18)
            self._play_btn.setCursor(Qt.PointingHandCursor)
            self._play_btn.setToolTip("播放语音")
            self._play_btn.setCheckable(True)
            self._play_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 5px;
                    font-size: 11px;
                    color: {MUTED};
                }}
                QPushButton:hover {{
                    background-color: {BG};
                }}
                QPushButton:checked {{
                    background-color: {ACCENT_SOFT};
                    color: {ACCENT};
                }}
            """)
            self._play_btn.clicked.connect(self._on_play_clicked)
            meta_row.addWidget(self._play_btn)
        if timestamp:
            meta = QLabel(timestamp)
            meta.setStyleSheet(
                f"color: {MUTED}; font-size: 10px; padding: 0 4px;"
            )
            meta_row.addWidget(meta)
        if role == "user":
            meta_row.addStretch()
        bubble_col.addLayout(meta_row)
```

类内新增方法：

```python
    def _on_play_clicked(self):
        if self._play_btn.isChecked():
            self.play_requested.emit(self._bubble.text(), self.msg_id)
        else:
            self.stop_requested.emit(self.msg_id)

    def set_playing(self, playing: bool):
        """播放状态驱动按钮外观（checked = 播放中）"""
        if self._play_btn is None:
            return
        self._play_btn.setChecked(playing)
        self._play_btn.setToolTip("停止" if playing else "播放语音")
```

同时把 `_build_ui` 里的 `bubble = SpeechBubble(text, role)` 改为 `self._bubble = SpeechBubble(text, role)`，`bubble_col.addWidget(bubble, ...)` 相应改为 `self._bubble`。

- [ ] **Step 4: 实现 chat_area.py 接线**

头部 import 追加：

```python
from shadowtalk.config.settings import Settings
from shadowtalk.core.tts_service import resolve_voice
from shadowtalk.ui.widgets.tts_player import get_player
```

类声明追加信号与状态（`message_sent` 之后）：

```python
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        ...
        self._friend_voice = ""
        self._player = get_player()
        self._player.playback_started.connect(self._on_player_started)
        self._player.playback_finished.connect(self._on_player_finished)
        self._player.playback_failed.connect(self._on_player_failed)
        self._player.synthesis_failed.connect(self._on_player_synth_failed)
```

set_friend_info 签名追加 voice：

```python
    def set_friend_info(self, friend_id: int, name: str, avatar_path: str = "", voice: str = ""):
        self._friend_voice = voice
        ...
```

add_message 追加 msg_id 参数并连接信号：

```python
    def add_message(self, text: str, role: str, timestamp: str, msg_id: int = 0):
        if role == "user":
            bubble = MessageBubble(
                text, role, timestamp,
                avatar_name="我", avatar_path="", avatar_variant="soft",
                msg_id=msg_id
            )
        else:
            bubble = MessageBubble(
                text, role, timestamp,
                avatar_name=self._avatar_name,
                avatar_path=self._avatar_path,
                avatar_variant="default",
                msg_id=msg_id
            )
            bubble.play_requested.connect(self._on_play_requested)
            bubble.stop_requested.connect(self._on_stop_requested)
        ...
```

clear_messages 开头追加 `self._player.stop()`。

新增槽（类内）：

```python
    def _on_play_requested(self, text: str, msg_id: int):
        """气泡按钮点播"""
        self._play_text(text, msg_id)

    def _on_stop_requested(self, msg_id: int):
        """播放中再点按钮 → 停止（规格 5.2）"""
        self._player.stop()

    def auto_play_ai_reply(self, text: str, msg_id: int):
        """AI 回复渲染后自动朗读（由 main_window 调用）"""
        self._play_text(text, msg_id)

    def _play_text(self, text: str, msg_id: int):
        voice = resolve_voice(self._friend_voice, Settings.get("tts_voice"))
        self._player.play(text, voice, msg_id)

    def _find_bubble(self, msg_id: int):
        """按消息 ID 找气泡 widget；找不到返回 None"""
        for i in range(self.message_list.count()):
            w = self.message_list.itemWidget(self.message_list.item(i))
            if getattr(w, "msg_id", None) == msg_id:
                return w
        return None

    def _on_player_started(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(True)

    def _on_player_finished(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)

    def _on_player_failed(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)
        self.status_message.emit("语音播放失败，已清除缓存，可重试")

    def _on_player_synth_failed(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)
        self.status_message.emit("语音合成失败，请检查网络")
```

- [ ] **Step 5: 实现 main_window.py**

`_load_history_messages`（164-169 行）传 msg_id：

```python
        for m in msgs:
            self.chat_area.add_message(m["content"], m["sender_type"], m["create_time"], m["id"])
```

`_on_friend_selected` 传好友音色：

```python
        if friend:
            name = friend["remark"] or friend["name"]
            self.chat_area.set_friend_info(friend_id, name, friend["avatar_path"], friend["voice"])
```

`__init__` 里信号连接区（`chat_area.message_sent.connect` 之后）加：

```python
        self.chat_area.status_message.connect(self._on_status_message)
```

`_on_ai_reply` 可见分支（295-305 行区域）改为先 insert 拿 id 再渲染，末尾接自动朗读：

```python
        msg_id = MessageRepository.insert(
            self.current_friend_id, "ai", reply,
            self._current_round_index(self.current_friend_id)
        )
        self.chat_area.add_message(reply, "ai", ts, msg_id)
        # 更新会话列表预览
        self.friend_list.set_last_message(
            self.current_friend_id,
            reply[:30],
            ts[-5:]
        )

        # ── 自动朗读 ──
        if Settings.get("tts_auto_play") == "1":
            self.chat_area.auto_play_ai_reply(reply, msg_id)
```

`_on_delete_friend` 中 `chat_area.clear_messages()` 已含 `player.stop()`，无需额外处理。类内新增槽：

```python
    def _on_status_message(self, msg: str):
        self.status_bar.showMessage(msg, 6000)
```

- [ ] **Step 6: 跑全部测试确认通过**

Run: `python -m pytest tests/test_chat_area.py tests/test_main_window.py -v`
Expected: PASS（既有测试不受影响 + 新增 4 个通过）

- [ ] **Step 7: 提交**

```bash
git add shadowtalk/ui/widgets/message_bubble.py shadowtalk/ui/widgets/chat_area.py shadowtalk/ui/main_window.py tests/test_chat_area.py
git commit -m "feat: add speaker button, auto-play hook, and status bar messages"
```

---

### Task 5: 设置面板"语音"Tab 与好友对话框音色

**Files:**
- Modify: `shadowtalk/ui/widgets/settings_dialog.py`（新 Tab + load/save）
- Modify: `shadowtalk/ui/widgets/friend_dialog.py`（音色下拉框 + get_data/fill）
- Modify: `shadowtalk/core/friend_service.py:13-40`（create 加 voice 参数并透传 FriendRepository.insert）
- Modify: `shadowtalk/ui/main_window.py:171-202`（_on_add_friend / _on_edit_friend 传 voice）
- Test: `tests/test_settings_dialog.py`（新建）、`tests/test_friend_dialog.py`（追加）、`tests/test_friend_service.py`（追加）

**Interfaces:**
- Consumes: `TTS_VOICES`、`Settings.get/set("tts_voice"|"tts_auto_play")`、`FriendDialog.get_data()["voice"]`
- Produces:
  - `SettingsDialog` 第三个 Tab「语音」：全局音色下拉（存 voice id）+ 自动朗读复选框
  - `FriendDialog` 表单「语音：」下拉：首项 `默认（跟随全局）`（data=""），其余为 TTS_VOICES label；`get_data()` 返回 `"voice"` 键

- [ ] **Step 1: 写失败测试**

```python
# tests/test_settings_dialog.py（新建）
import sys
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from shadowtalk.config.settings import Settings
from shadowtalk.core.tts_service import TTS_VOICES
from shadowtalk.ui.widgets.settings_dialog import SettingsDialog


def test_voice_tab_populated_from_tts_voices():
    dlg = SettingsDialog()
    assert dlg.voice_combo.count() == len(TTS_VOICES)
    # 下拉显示 label，数据为 voice id
    assert dlg.voice_combo.itemData(0) == TTS_VOICES[0]["voice"]
    assert dlg.voice_combo.currentText() != ""


def test_voice_tab_loads_and_saves():
    Settings.set("tts_voice", "zh-CN-YunxiNeural")
    Settings.set("tts_auto_play", "1")
    dlg = SettingsDialog()
    dlg._load_settings()
    assert dlg.voice_combo.currentData() == "zh-CN-YunxiNeural"
    assert dlg.auto_play_check.isChecked()

    dlg.voice_combo.setCurrentIndex(dlg.voice_combo.findData("en-US-AriaNeural"))
    dlg.auto_play_check.setChecked(False)
    dlg._on_save()
    assert Settings.get("tts_voice") == "en-US-AriaNeural"
    assert Settings.get("tts_auto_play") == "0"
```

```python
# tests/test_friend_dialog.py 追加
def test_friend_dialog_voice_combo():
    dlg = FriendDialog()
    assert dlg.voice_combo.count() == len(TTS_VOICES) + 1  # 首项"默认"
    assert dlg.voice_combo.itemData(0) == ""
    dlg.voice_combo.setCurrentIndex(dlg.voice_combo.findData("zh-CN-YunxiNeural"))
    assert dlg.get_data()["voice"] == "zh-CN-YunxiNeural"


def test_friend_dialog_voice_default():
    dlg = FriendDialog()
    assert dlg.get_data()["voice"] == ""
```

```python
# tests/test_friend_service.py 追加
def test_create_passes_voice():
    fid = FriendService.create(name="v", remark="", system_prompt="",
                               voice="zh-CN-YunxiNeural")
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-YunxiNeural"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_settings_dialog.py tests/test_friend_dialog.py tests/test_friend_service.py -v`
Expected: FAIL（`AttributeError: 'SettingsDialog' object has no attribute 'voice_combo'` / `FriendService.create` 收到未预期的 `voice` 参数）

- [ ] **Step 3: 实现 settings_dialog.py**

import 区加：

```python
from shadowtalk.core.tts_service import TTS_VOICES
```

_build_ui 中「数据操作」Tab 之后、`layout.addWidget(tabs)` 之前插入：

```python
        # Tab 3: Voice
        voice_tab = QWidget()
        voice_layout = QFormLayout()
        self.voice_combo = QComboBox()
        for v in TTS_VOICES:
            self.voice_combo.addItem(v["label"], v["voice"])
        self.auto_play_check = QCheckBox("AI 回复到达后自动朗读")
        voice_layout.addRow("默认语音：", self.voice_combo)
        voice_layout.addRow("自动朗读：", self.auto_play_check)
        voice_tab.setLayout(voice_layout)
        tabs.addTab(voice_tab, "语音")
```

（原「数据操作」tab 变量名为 op_tab，保留；Tab 顺序变为 API/记忆/语音/数据操作）

_load_settings 末尾加：

```python
        idx = self.voice_combo.findData(Settings.get("tts_voice"))
        self.voice_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.auto_play_check.setChecked(Settings.get("tts_auto_play") == "1")
```

_on_save 末尾加：

```python
        Settings.set("tts_voice", self.voice_combo.currentData() or "zh-CN-XiaoxiaoNeural")
        Settings.set("tts_auto_play", "1" if self.auto_play_check.isChecked() else "0")
```

import 区补 `QComboBox, QCheckBox`（QWidgets import 行）。

- [ ] **Step 4: 实现 friend_dialog.py**

import 区加：

```python
from shadowtalk.core.tts_service import TTS_VOICES
```

表单中「工作目录」行之后（91 行附近）插入：

```python
        self.voice_combo = QComboBox()
        self.voice_combo.addItem("默认（跟随全局）", "")
        for v in TTS_VOICES:
            self.voice_combo.addItem(v["label"], v["voice"])
        self.voice_combo.setStyleSheet(_input_style())
        form.addRow("语音：", self.voice_combo)
```

_fill_data 末尾加：

```python
        if friend["voice"]:
            idx = self.voice_combo.findData(friend["voice"])
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
```

get_data 返回 dict 加 `"voice": self.voice_combo.currentData() or "",`

import 区补 `QComboBox`。

- [ ] **Step 5: 实现 friend_service.py 与 main_window.py 传参**

friend_service.py `create` 签名与透传：

```python
    @staticmethod
    def create(name: str, remark: str, system_prompt: str,
               avatar_source_path: str = "",
               ai_role: str = "", user_role: str = "", work_dir: str = "",
               voice: str = "") -> int:
        ...
        friend_id = FriendRepository.insert(
            name, remark, system_prompt, avatar_path,
            ai_role=ai_role, user_role=user_role, work_dir=work_dir,
            voice=voice
        )
```

main_window：_on_add_friend（171-184）FriendService.create 调用加 `voice=data.get("voice", "")`；
_on_edit_friend（186-202）FriendRepository.update 调用加 `voice=data.get("voice", "")`。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_settings_dialog.py tests/test_friend_dialog.py tests/test_friend_service.py tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add shadowtalk/ui/widgets/settings_dialog.py shadowtalk/ui/widgets/friend_dialog.py shadowtalk/core/friend_service.py shadowtalk/ui/main_window.py tests/test_settings_dialog.py tests/test_friend_dialog.py tests/test_friend_service.py
git commit -m "feat: add voice tab to settings and voice picker to friend dialog"
```

---

### Task 6: 全量回归与人工验证清单

**Files:**
- 无新增（若全量回归暴露回归则修复并提交）

- [ ] **Step 1: 全量跑测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS（含既有 100+ 测试与新增测试）

- [ ] **Step 2: 人工验证清单（运行应用 `python -m shadowtalk.main`）**

1. 打开与任意好友的聊天，AI 回复的气泡时间戳左侧出现 🔊 按钮；自己消息没有
2. 点击 🔊：按钮变绿（checked），约 1-3 秒后开始播放（晓晓女声）；再点停止
3. 点播放后立刻点另一条消息的 🔊：旧语音被打断，新语音播放
4. 播放完：按钮自动复位
5. 设置 → 语音 Tab：改默认语音为"云希（男）"并勾选自动朗读 → 保存 → 发消息：AI 回复自动用男声朗读
6. 好友对话框：给某好友选"晓伊"，与该好友聊天自动朗读为女声；取消勾选自动朗读后手动点播仍用好友音色
7. 断网后点播放：按钮复位，状态栏出现"语音合成失败，请检查网络"，聊天功能不受影响
8. 重播同一条消息：无重新合成等待（缓存命中，立即播放）
9. 切换好友：正在播放的语音停止

- [ ] **Step 3: 收尾提交（若有修复）**

```bash
git status
git add -A
git commit -m "fix: tts regression fixes from full test run"   # 仅在有变更时执行
```
