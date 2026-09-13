# ShadowTalk 影聊 — 聊天界面设计规格

> 日期：2026-08-11
> 版本：V1.0 第三轮
> 状态：待审核
> 范围：PySide6 聊天界面、消息气泡、AI 异步调用、好友对话框

---

## 1. 概述

本轮设计覆盖 ShadowTalk 的 UI 层实现，包括：
- 主窗口布局（左侧好友列表 + 右侧聊天区）
- 消息气泡组件（user / ai / loading 三种状态）
- AI 异步调用（QThread 工作线程，不阻塞 UI）
- 好友新增/编辑对话框
- 完整的消息发送与接收流程

### 1.1 设计原则

- **UI 可替换**：UI 层为薄壳，业务逻辑零 UI 依赖
- **非流式一次性渲染**：AI 完整接收后一次性展示，无打字动画
- **异步调用**：AI 请求在工作线程执行，UI 永不阻塞
- **信号槽通信**：线程间通过 Signal 传递结果，避免直接操作 UI 控件

### 1.2 分层约束（强制）

```
依赖方向（单向）：
  ui/ → core/ → data/

禁止：
  ❌ core/ 中 import PySide6
  ❌ ui/ 被 core/ 引用
  ❌ UI 层直接操作 Database
  ❌ UI 线程中调用 AI API
```

---

## 2. 文件结构

```
ui/
├── __init__.py
├── main_window.py              # 主窗口
├── widgets/
│   ├── __init__.py
│   ├── friend_list.py          # 好友列表
│   ├── chat_area.py            # 聊天区域（消息列表 + 输入框）
│   ├── message_bubble.py       # 单条消息气泡
│   └── friend_dialog.py        # 新增/编辑好友对话框
└── threads/
    ├── __init__.py
    └── ai_worker.py            # AI 调用工作线程
```

---

## 3. 主窗口布局

```
┌─────────────────────────────────────────────────────────┐
│  ShadowTalk                                    [_][□][X] │
├────────────┬────────────────────────────────────────────┤
│            │  昵称：小明                                │
│  好友列表  │  ┌──────────────────────────────────────┐  │
│            │  │  2026-08-11 14:30                    │  │
│  ┌──────┐  │  │          ┌──────────────┐           │  │
│  │头像1 │  │  │          │ 你好！       │ (user)    │  │
│  │ 小明  │  │  │          └──────────────┘           │  │
│  └──────┘  │  │  ┌──────────────┐                    │  │
│  ┌──────┐  │  │  │ 嗨，很高兴   │ (ai)               │  │
│  │头像2 │  │  │  │ 认识你！     │                    │  │
│  │ 小红  │  │  │  └──────────────┘                    │  │
│  └──────┘  │  │          ┌──────────────┐           │  │
│            │  │          │ 你叫什么？   │ (user)    │  │
│  [+ 新增]  │  │          └──────────────┘           │  │
│            │  │  ┌─ 正在回复… ──────────────────────┐│  │
│            │  │  │ (加载提示，等待 AI 返回)         ││  │
│            │  │  └──────────────────────────────────┘│  │
│            │  └──────────────────────────────────────┘  │
│            │  ┌────────────────────────┬──────────┐     │
│            │  │ 输入消息...            │ 发送     │     │
│            │  └────────────────────────┴──────────┘     │
├────────────┴────────────────────────────────────────────┤
│  状态栏：记忆引擎运行中 | L0: 12轮 | L1: 2条            │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 消息气泡

### 4.1 message_bubble.py

```python
class MessageBubble(QWidget):
    """单条消息气泡：区分 user / ai / loading 三种状态"""
    
    def __init__(self, text: str, role: str, timestamp: str, parent=None):
        """
        role: "user" | "ai" | "loading"
        """
        super().__init__(parent)
        self._role = role
        self.setLayout(self._build_layout(text, role, timestamp))
        self._apply_style(role)
```

| 状态 | 对齐 | 样式 |
|---|---|---|
| user | 右对齐 | 蓝色背景 |
| ai | 左对齐 | 灰/绿色背景 |
| loading | 左对齐 | 斜体灰字"正在回复…" |

### 4.2 加载状态

- 发送后立即显示"正在回复…"
- 发送按钮禁用（防止重复发送）
- AI 回复到达后移除加载提示，恢复按钮

---

## 5. AI 异步调用

### 5.1 ai_worker.py — QThread 工作线程

```python
class AIWorker(QThread):
    """AI 调用工作线程"""
    
    finished = Signal(str)      # AI 回复文本
    failed = Signal(str)        # 错误信息
    
    def __init__(self, friend_id, user_message, ai_client, memory_engine):
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.ai_client = ai_client
        self.memory_engine = memory_engine
    
    def run(self):
        try:
            messages = self.memory_engine.build_context(
                self.friend_id, self.user_message
            )
            reply = self.ai_client.chat(messages)
            self.finished.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))
```

### 5.2 ai_client.py — AI 客户端（纯 Python）

```python
class AIClient:
    """封装 OpenAI 兼容接口，纯 Python 无 UI 依赖"""
    
    def __init__(self, base_url, api_key, model, temperature=0.7, max_tokens=2000):
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def chat(self, messages: list[dict]) -> str:
        """非流式调用，返回完整回复文本"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        return response.choices[0].message.content
```

---

## 6. 发送流程

```
用户点击发送 / 回车
  ↓
ChatArea._on_send()
  ↓
1. 添加用户消息气泡（直接显示）
  ↓
2. 保存用户消息到数据库
  ↓
3. 显示"正在回复…"加载提示 + 禁用发送按钮
  ↓
4. 创建 AIWorker 线程并启动
  ↓
5. AIWorker.run() 后台执行：
   ├── memory_engine.build_context()     ← 组装上下文
   ├── ai_client.chat(messages)          ← 调用 AI API（非流式）
   └── finished.emit(reply)               ← 发射完成信号
  ↓
6. UI 线程收到 finished 信号：
   ├── 移除加载提示
   ├── 添加 AI 回复气泡（一次性完整显示）
   ├── 保存 AI 回复到数据库
   └── 恢复发送按钮
  ↓
7. 失败时：
   └── hide_loading() + 显示错误气泡
```

### 消息保存时机

| 消息 | 保存时机 | 轮次编号 |
|---|---|---|
| 用户消息 | 发送后立即保存 | 当前最大 round_index + 1 |
| AI 回复 | 收到完整回复后保存 | 与对应用户消息相同 round_index |

**一轮 = 一条用户消息 + 一条 AI 回复，共享同一个 round_index**。

---

## 7. 好友对话框

### 7.1 friend_dialog.py

```python
class FriendDialog(QDialog):
    """新增/编辑好友对话框"""
    
    字段：
    - 昵称（QLineEdit）
    - 备注（QLineEdit）
    - AI人设Prompt（QTextEdit，多行）
    - 头像（QFileDialog 选择图片文件）
    
    get_data() -> dict:
    {
        "name": str,
        "remark": str,
        "system_prompt": str,
        "avatar_path": str,
    }
```

---

## 8. 主窗口

### 8.1 main_window.py

```python
class MainWindow(QMainWindow):
    """主窗口：左侧好友列表 + 右侧聊天区域"""
    
    初始化：
    - 创建 AIClient（从 Settings 读取配置）
    - 组装 FriendListWidget + ChatArea
    - 连接信号槽
    - 加载好友列表
    
    信号连接：
    - friend_list.friend_selected → _on_friend_selected
    - chat_area.message_sent → _on_message_sent
    - ai_worker.finished → _on_ai_reply
    - ai_worker.failed → _on_ai_failed
```

---

## 9. 待后续轮次覆盖

本轮**不涉及**：
- 设置面板（第四轮）
- 好友列表 Widget 的详细实现（第三轮聚焦聊天区，好友列表为简化占位）
