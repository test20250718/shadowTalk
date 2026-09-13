# ShadowTalk 影聊 — 深色模式设计规格

> 日期：2026-08-14
> 版本：V1.0 新增
> 状态：待审核
> 范围：设置里提供浅色/深色两档界面主题，即时切换、持久化

---

## 1. 概述

为 ShadowTalk 增加界面主题切换：设置对话框新增"外观"页，用户可在**浅色 / 深色**两档之间选择，保存后**即时生效**（无需重启），选择持久化到数据库。

### 1.1 需求确认（用户已确认）

| 问题 | 决定 |
|---|---|
| 模式选项 | 仅「浅色 / 深色」两档（不做跟随系统、不做定时） |
| 生效时机 | 即时生效（保存后界面立即切换，列表滚动位置重置可接受） |
| 实现方案 | 主题模块（theme.py 定义两套配色，控件动态取色） |
| 深色风格 | 微信深色风格：深灰底、暖白字、绿色强调，用户消息绿泡 |

### 1.2 设计原则

- **颜色单一来源**：所有 UI 颜色定义在 `shadowtalk/ui/theme.py`，控件渲染时从"当前主题"取色；不再有模块级静态颜色常量被跨文件 import
- **即时切换 = 重建可见内容**：主题切换时重设全局 QSS 并重建好友列表与消息列表（item widget 每次构造取色，天然跟随新主题）
- **持久化**：`theme` 设置项写入 app_config 表，启动时先应用再构造 UI

### 1.3 分层约束（强制，沿用现有规格）

```
依赖方向（单向）：
  ui/ → core/ → data/

禁止：
  ❌ core/ 中 import PySide6（theme 属 ui 层，不进 core）
  ❌ 主题切换影响聊天数据（仅重建显示，不触碰数据库）
```

---

## 2. 配色方案

### 2.1 颜色字段（Theme 数据类，14 个）

| 字段 | 用途 | 浅色 LIGHT（=现有） | 深色 DARK |
|---|---|---|---|
| `BG` | 聊天区背景 | `#F9F8F6` | `#1A1A1E` |
| `SURFACE` | 侧栏/头部/输入卡/菜单 | `#FFFFFF` | `#26262B` |
| `FG` | 主文字 | `#37352F` | `#E8E6E1` |
| `MUTED` | 次要文字 | `#A09B8C` | `#8F8C85` |
| `BORDER` | 边框 | `#E5E2DB` | `#3A3A40` |
| `ACCENT` | 强调绿（发送按钮/选中态） | `#2E9E57` | `#34C274` |
| `ACCENT_SOFT` | 选中浅绿底 | `#E4F2EA` | `#1E3A2A` |
| `SOFT` | 浅色头像底 | `#E8E5DE` | `#3A3A40` |
| `USER_BUBBLE` | 自己消息气泡 | `#37352F` | `#2E9E57` |
| `USER_FG` | 自己消息文字 | `#FFFFFF` | `#FFFFFF` |
| `AI_BUBBLE` | 对方消息气泡 | `#FFFFFF` | `#2E2E34` |
| `AI_FG` | 对方消息文字 | `#37352F` | `#E8E6E1` |
| `SCROLL_HANDLE` | 滚动条滑块 | `#C9C5BC` | `#4A4A52` |
| `SCROLL_HANDLE_HOVER` | 滚动条滑块悬停 | `#A8A398` | `#5A5A62` |

### 2.2 说明

- 浅色值与现有 `message_bubble.py` 常量完全一致，浅色外观零变化
- 深色下用户消息气泡改绿色（微信深色同款），AI 气泡深灰带边框

---

## 3. 文件结构与职责

```
shadowtalk/
├── ui/
│   ├── theme.py                    # 新建：Theme 数据类、LIGHT/DARK、current()/set_current()、global_qss()
│   └── widgets/
│       ├── message_bubble.py       # 改：删除模块级颜色常量，paint/构造处改用 theme.current()
│       ├── chat_area.py            # 改：import 与 QSS 拼接改动态取色
│       ├── friend_list.py          # 改：同上
│       ├── emoji_panel.py          # 改：同上（仅 SURFACE/BORDER/BG 三处）
│       ├── friend_dialog.py        # 改：2 处直接色值改动态取色
│       └── settings_dialog.py      # 改：新增"外观"tab（主题下拉 + 保存 + theme_changed 信号）
├── ui/main_window.py               # 改：全局 QSS 用 theme.global_qss()；连接 theme_changed；_apply_theme()
└── config/settings.py              # 改：DEFAULTS 增加 "theme": "light"
```

### 3.1 theme.py 接口

```python
@dataclass(frozen=True)
class Theme:
    name: str                       # "light" | "dark"
    BG: str; SURFACE: str; FG: str; MUTED: str; BORDER: str
    ACCENT: str; ACCENT_SOFT: str; SOFT: str
    USER_BUBBLE: str; USER_FG: str; AI_BUBBLE: str; AI_FG: str
    SCROLL_HANDLE: str; SCROLL_HANDLE_HOVER: str

LIGHT = Theme(...)                  # 2.1 表浅色列
DARK = Theme(...)                   # 2.1 表深色列

def current() -> Theme: ...         # 当前主题
def set_current(name: str) -> None  # "light" | "dark"，非法值回落浅色
def global_qss() -> str:            # 主窗口全局 QSS（QMainWindow/MenuBar/QMenu/QSplitter/QStatusBar），
                                    # 内容即现有 main_window.py 55-96 行样式，颜色改取当前主题
```

### 3.2 取色改造模式

所有引用颜色处改为函数调用取当前主题：

```python
# 旧：from shadowtalk.ui.widgets.message_bubble import BG, SURFACE, ...
# 新：
from shadowtalk.ui.theme import current as theme_current
...
t = theme_current()
style = f"background-color: {t.SURFACE}; color: {t.FG};"
```

涉及点：
- **message_bubble.py**：`AvatarLabel._bg_color/_text_color/_render`、`TypingIndicator.paintEvent`、SpeechBubble 两角色 QSS、ApprovalCard QSS、DayDivider QSS、meta 行 QSS —— 原文件头 14 个模块级颜色常量**删除**
- **chat_area.py**：头部 QSS、消息列表 QSS、输入卡/输入框/发送按钮 QSS、滚动条 QSS
- **friend_list.py**：品牌头部、搜索框、列表、按钮 QSS
- **emoji_panel.py**：SURFACE/BORDER/BG 三处
- **friend_dialog.py**：2 处直接色值
- **main_window.py**：55-96 行全局 QSS 改为 `self.setStyleSheet(theme.global_qss())`

### 3.3 设置入口（settings_dialog.py）

- 新增"外观" tab：`QComboBox`（浅色/深色，data 为 "light"/"dark"），回填 `Settings.get("theme")`
- 保存：`Settings.set("theme", ...)` 后 `self.theme_changed.emit(新主题名)`（新类信号）
- 信号由 main_window 连接（见 3.4）；对话框自身关闭，下次打开构造时取新主题色

### 3.4 主窗口接线（main_window.py）

```python
# _on_open_settings 中（构造对话框后、exec 前连接）：
dialog = SettingsDialog(self, self.current_friend_id)
dialog.theme_changed.connect(self._on_theme_changed)
dialog.exec()

def _on_theme_changed(self, name: str):
    theme.set_current(name)
    self._apply_theme()

def _apply_theme(self):
    self.setStyleSheet(theme.global_qss())
    self.friend_list.restyle()                    # 容器样式按当前主题重设（侧栏背景/品牌头/搜索框/列表/操作按钮）
    self.chat_area.restyle()                      # 容器样式按当前主题重设（背景/头部/消息列表/输入卡/按钮）+ 头部头像重绘 + emoji_panel.restyle()
    self._load_friends()                          # 重建好友列表（保留预览字典）
    if self.current_friend_id:
        self.chat_area.clear_messages()
        self._load_history_messages(self.current_friend_id)
```

### 3.5 启动应用

main.py 在创建 MainWindow **之前**：`theme.set_current(Settings.get("theme"))`。

---

## 4. 数据流

```
设置对话框保存 ──→ Settings.set("theme", "dark")   （app_config 持久化）
      │
      └── theme_changed 信号 ──→ MainWindow._on_theme_changed
                                      ├── theme.set_current("dark")
                                      ├── setStyleSheet(global_qss())     ← 菜单栏/状态栏等
                                      ├── friend_list.restyle()           ← 侧栏容器样式重设
                                      ├── chat_area.restyle()             ← 聊天容器样式重设（含表情面板/头部头像）
                                      ├── _load_friends()                 ← 好友列表重建取新色
                                      └── clear + 重载当前好友消息         ← 气泡重建取新色

启动 ──→ main.py: theme.set_current(Settings.get("theme")) → 构造 UI
```

## 5. 错误处理

- `Settings.get("theme")` 非法值/缺失：`set_current` 回落浅色（现有 INSERT OR IGNORE 默认 light）
- 主题切换不影响聊天数据：仅重建显示层，数据库零接触
- 切换瞬间播放中的 TTS 会停止（clear_messages 调用播放器 stop——与切换好友行为一致，属已知接受行为）

## 6. 测试

| 用例 | 断言 |
|---|---|
| theme 字段齐全 | LIGHT/DARK 各 14 字段非空，LIGHT 与旧常量值一致（BG=#F9F8F6 等抽查） |
| set_current/current | set("dark")→current().name=="dark"；set("非法")→回落 light |
| global_qss 含主题色 | 深色下 global_qss() 含 "#26262B"（SURFACE） |
| 设置对话框主题下拉 | 存在"外观"tab；保存写 Settings("theme")；回填当前值 |
| 容器样式跟随主题 | _apply_theme/restyle 后 chat_area.styleSheet 含 DARK.BG(#1A1A1E)、friend_list.styleSheet 含 DARK.SURFACE(#26262B)、会话项名称标签取 DARK.FG(#E8E6E1)、emoji_panel 重设为深色 |
| 气泡渲染取当前主题 | ChatArea.add_message 后气泡 QSS/绘制色来自 theme.current()（浅色下含 #37352F 用户泡色；切深色重建后含 #2E9E57） |
| 全量回归 | 既有 137 测试不回归 |

## 7. 明确不做（YAGNI）

- ❌ 跟随系统主题
- ❌ 定时自动切换
- ❌ 主题色自定义/编辑
- ❌ 对话框（设置/好友编辑）打开状态下实时换肤——关闭后下次打开生效
