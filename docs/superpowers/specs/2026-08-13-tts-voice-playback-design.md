# ShadowTalk 影聊 — 语音播报（TTS）设计规格

> 日期：2026-08-13
> 版本：V1.1 新增
> 状态：待审核
> 范围：AI 回复语音朗读、edge-tts 合成、QMediaPlayer 播放、好友音色配置

---

## 1. 概述

为 ShadowTalk 增加"AI 说的话用语音播放"能力：AI 消息气泡上提供手动播放按钮，设置面板提供自动朗读开关，每个好友可单独指定音色。

### 1.1 需求确认（用户已确认）

| 问题 | 决定 |
|---|---|
| 使用位置 | ShadowTalk 聊天界面朗读 AI 回复 |
| 语音引擎 | edge-tts 在线神经语音（晓晓/云希等，免费无 API key，需联网） |
| 触发方式 | 手动点播（气泡喇叭按钮）+ 设置里可选的自动朗读 |
| 音色配置 | 全局默认音色 + 每个好友可单独指定 |

### 1.2 设计原则

- **core 零 Qt 依赖**：合成与缓存逻辑在 core 层为纯 Python，可单测；QMediaPlayer 等 Qt 依赖只在 ui 层
- **UI 永不阻塞**：edge-tts 网络合成在工作线程执行
- **同时只服务一条**：单播放器实例，新播放打断旧播放，合成任务同样只保留最新
- **缓存优先**：同一消息重播不重复联网合成

### 1.3 分层约束（强制，沿用现有规格）

```
依赖方向（单向）：
  ui/ → core/ → data/

禁止：
  ❌ core/ 中 import PySide6
  ❌ UI 线程中执行网络合成
  ❌ 缓存目录写入失败时影响聊天主流程（只提示，不崩溃）
```

---

## 2. 文件结构

```
shadowtalk/
├── core/
│   └── tts_service.py           # 纯 Python：音色清单、音色解析、edge-tts 合成、缓存
└── ui/
    ├── threads/
    │   └── tts_worker.py        # QThread 工作线程：调合成、发回结果信号
    └── widgets/
        └── tts_player.py        # QMediaPlayer 单例播放器（QtMultimedia）
```

改动（不新建）：
- `shadowtalk/models/entities.py` — `Friend` 加 `voice: str = ""`
- `shadowtalk/data/database.py` — friends 表迁移加 `voice` 列
- `shadowtalk/config/settings.py` — `DEFAULTS` 加 `tts_voice`、`tts_auto_play`
- `shadowtalk/ui/widgets/message_bubble.py` — AI 气泡加喇叭按钮
- `shadowtalk/ui/widgets/chat_area.py` — 接入播放/停止信号、自动朗读触发
- `shadowtalk/ui/widgets/settings_dialog.py` — 新增"语音"Tab
- `shadowtalk/ui/widgets/friend_dialog.py` — 好友编辑加语音下拉框
- `requirements.txt` — 加 `edge-tts>=6.1.0`

---

## 3. 数据流

### 3.1 手动播放

```
用户点 AI 气泡喇叭按钮
  → MessageBubble.play_requested(text, msg_id, friend_id) 信号
  → ChatArea → TtsPlayer.play(text, voice, msg_id)
  → TtsPlayer：
      1. 查缓存 data/tts_cache/{msg_id}.mp3，命中直接播
      2. miss → 起 TtsWorker（QThread）调 core 层合成 → 落盘 → 播放
  → 播放状态经信号广播，按钮切换 ▶/⏹ 状态
```

### 3.2 自动朗读

```
AI 回复到达（main_window 收到 ai_worker 结果、add_message 之后）
  → 若 Settings.get("tts_auto_play") == "1" → 同样走 TtsPlayer.play()
  → 新播放打断当前播放（单实例语义）
```

### 3.3 音色解析

```
resolve_voice(friend_voice, global_voice)：
  friend_voice 非空且在 TTS_VOICES 中 → 用 friend_voice
  否则 global_voice（默认 zh-CN-XiaoxiaoNeural）
  均无效 → 回退 TTS_VOICES[0]
```

---

## 4. core 层：tts_service.py

纯 Python，禁止 import PySide6。提供：

- `TTS_VOICES: list[dict]` — `{"label": "晓晓（女·温柔）", "voice": "zh-CN-XiaoxiaoNeural"}` 等约 10 个音色（中文 6-8 个 + 英文 2-3 个），下拉框与校验共用此常量
- `DEFAULT_VOICE` — `zh-CN-XiaoxiaoNeural`
- `resolve_voice(friend_voice: str, global_voice: str) -> str`
- `cache_path(msg_id: int) -> Path` — `data/tts_cache/{msg_id}.mp3`
- `synthesize(text: str, voice: str, out_path: Path)` — 调 `edge_tts.Communicate(text, voice).save(out_path)`；空文本直接返回
- `remove_cached(msg_id: int)` — 播放失败时清掉损坏缓存

缓存目录：`shadowtalk/data/tts_cache/`，启动时确保存在；按消息 ID 全局唯一自增，不同好友无冲突；好友聊天记录清空/删除时不主动清缓存文件（体积小）。

---

## 5. ui 层：播放与按钮

### 5.1 tts_player.py

`TtsPlayer(QObject)` 单例（模块级 `player = TtsPlayer()`）：
- 内部 `QMediaPlayer` + `QAudioOutput`，音频输出跟随系统默认设备
- `play(text, voice, msg_id)`：缓存命中直接播；miss 则起 `TtsWorker`（QThread）后台合成，成功回调继续播、失败发 `synthesis_failed(msg_id)` 信号
- 内部状态机：空闲 / 合成中 / 播放中；任何新 `play()` 调用都打断当前（先停止当前 QThread 合成任务与播放）
- 信号：`playback_started(msg_id)`、`playback_finished(msg_id)`、`playback_failed(msg_id)`、`synthesis_failed(msg_id)`

### 5.2 喇叭按钮（message_bubble.py）

- 仅 AI 消息显示；位于气泡元信息行（时间戳左侧），尺寸约 18px 图标按钮，透明底、hover 浅灰、播放中绿色
- 点击：本消息未在播 → `play_requested`；正在播本消息 → 停止；其他消息在播 → 打断并播本消息
- 按钮状态由 TtsPlayer 信号驱动（按 msg_id 匹配），消息滚动出可视区后按钮状态自然保留

### 5.3 接线（chat_area.py / main_window.py）

- ChatArea 持有 TtsPlayer 引用，`MessageBubble.play_requested` 转发到 TtsPlayer
- main_window 在 AI 回复渲染完成后判断自动朗读（只对最新一条 AI 回复自动触发）
- 切换好友时停止当前播放（避免切走后还在响）

---

## 6. 配置与数据

### 6.1 app_config 新增键（settings.py DEFAULTS）

| key | 默认值 | 说明 |
|---|---|---|
| `tts_voice` | `zh-CN-XiaoxiaoNeural` | 全局默认音色（存 voice id） |
| `tts_auto_play` | `0` | 自动朗读开关（`1` 开 / `0` 关） |

### 6.2 friends 表迁移（database.py，沿用现有模式）

```python
existing = {row[1] for row in conn.execute("PRAGMA table_info(friends)")}
if "voice" not in existing:
    conn.execute("ALTER TABLE friends ADD COLUMN voice TEXT DEFAULT ''")
```

`Friend` 数据类加 `voice: str = ""`；`FriendRepository` 读写该列。

### 6.3 设置面板"语音"Tab

- 全局默认音色：下拉框（label 显示，存 voice id）
- 自动朗读：复选框
- 好友编辑对话框：语音下拉框（首项"默认（跟随全局）" + TTS_VOICES 全量），不选 = 全局默认

---

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 合成失败（断网/edge-tts 异常） | 按钮复位，ChatArea 状态栏提示"语音合成失败，请检查网络"；不弹阻塞对话框 |
| 播放失败（文件损坏） | 复位 + 提示，并 `remove_cached` 删掉损坏缓存（下次重播重新合成） |
| 空内容/纯表情 | 点播直接忽略，不发起合成 |
| 合成中途被打断 | TtsWorker 退出标志置位，结果丢弃不播放 |
| 缓存目录不可写 | 不崩溃；降级为"合成后不落盘、直接播放"（TtsPlayer 持有临时文件路径播放），并提示一次"语音缓存不可用" |

---

## 8. 测试（tests/，pytest）

- `test_tts_service.py`：
  - `resolve_voice`：好友指定 > 全局 > 默认兜底；非法值回退
  - `synthesize`：mock `edge_tts.Communicate`，验证被调用且空文本直接返回不调用
  - 缓存：`cache_path` 路径正确；合成产物按 msg_id 落盘
- 迁移断言：老库文件打开后 `friends` 含 `voice` 列（现有迁移逻辑补断言）
- UI 播放状态切换不写 Qt 测试（项目无 Qt 测试先例，人工验证）

---

## 9. 已知边界

- edge-tts 为社区封装微软 Edge 在线接口，非官方 API；若微软变更接口可能失效，届时需更换音源（本设计将合成收敛在 `tts_service.synthesize` 单点，便于替换）
- 需联网；断网时手动点播提示失败，不影响聊天主流程
- 音频输出跟随系统默认输出设备，无独立音量/设备选择（YAGNI）
