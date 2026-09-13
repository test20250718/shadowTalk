# ShadowTalk 邮箱客户端设计

**日期**：2026-08-27
**状态**：已确认
**版本**：V1.5-Add

## 概述

在 ShadowTalk 中加入通用邮箱客户端，参考微信在界面左侧加一个垂直图标 Tab，切换「聊天」与「邮箱」两个视图。首版极简：IMAP 收信 + 邮件列表 + 正文阅读 + SMTP 纯文本写信。

本功能独立于现有的「数字分身邮件同步」系统，两者共享 SMTP/IMAP 配置参数，但数据表、worker、UI 完全隔离。

## 整体布局

### 主窗口重构

现有 `QSplitter` 从 2 栏重构为 3 栏，左侧新增垂直图标 Tab 栏，左右两面板改为 `QStackedWidget` 随 Tab 同步切换：

```
MainWindow (QMainWindow)
├── MenuBar
├── CentralWidget: QSplitter(Qt.Horizontal), handle 5px
│   ├── [0] VerticalTabBar ........ 50px, stretch 0, fixed
│   │     💬 聊天 / 📧 邮箱（图标按钮，微信式）
│   ├── [1] LeftPanel (QStackedWidget) .. 280px, stretch 0
│   │     ├── Page 0: FriendListWidget（现有，零修改）
│   │     └── Page 1: MailFolderListWidget（新）
│   └── [2] RightPanel (QStackedWidget) . stretch 1
│         ├── Page 0: ChatArea（现有，零修改）
│         └── Page 1: MailWidget（新：邮件列表 + 阅读窗格）
└── StatusBar
```

### 切换逻辑

`VerticalTabBar.tab_changed(index)` → MainWindow 同步设置 `LeftPanel.setCurrentIndex(index)` + `RightPanel.setCurrentIndex(index)`。两个堆叠 widget 始终保持同 index。

### MailWidget 内部布局

`MailWidget` 内部用水平 `QSplitter`：
- 左侧 ~60%：邮件列表（`QTableWidget` 或自定义 `QListWidget`，列 = 发件人 / 主题 / 时间）
- 右侧 ~40%：阅读窗格（`QTextEdit` read-only，显示正文 + 头部元信息）
- 顶部工具栏：「刷新」「写信」两个按钮
- 未选中邮件时阅读窗格显示空状态「选择一封邮件阅读」

### 现有组件零修改

`FriendListWidget` 和 `ChatArea` 被原样放进 `QStackedWidget` 作为 page 0，代码不动。所有邮件功能是新 Widget。

## 新增文件

| 文件 | 职责 |
|------|------|
| `ui/widgets/vertical_tab_bar.py` | 左侧垂直图标 Tab 栏（💬/📧） |
| `ui/widgets/mail_folder_list.py` | 邮箱文件夹列表（收件箱/已发送…） |
| `ui/widgets/mail_widget.py` | 邮箱主面板：邮件列表 + 阅读窗格 |
| `ui/widgets/mail_compose_dialog.py` | 写信对话框（纯文本） |
| `ui/threads/mail_fetch_worker.py` | IMAP 拉取线程 |
| `core/mail_cache.py` | 邮件缓存逻辑（纯 Python，无 PySide6 依赖） |

`data/repositories.py` 扩展 `MailCacheRepository` 类。

## 数据库

新增 `mail_cache` 表（邮件本地缓存）：

```sql
CREATE TABLE IF NOT EXISTS mail_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL DEFAULT 'INBOX',
    message_id TEXT NOT NULL,
    sender TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    sender_addr TEXT DEFAULT '',
    body_text TEXT DEFAULT '',
    received_at TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(folder, message_id)
);
```

`processed_emails` 表继续给分身同步专用，与 `mail_cache` 互不干扰。

## 数据流

### 配置

复用设置里现有的 SMTP/IMAP 参数（`mail_imap_host/user/password`、`mail_smtp_host/port/user/password`），不引入新配置项。邮箱是通用客户端，不使用 MailHog 开发模式。

### 收信流程

```
用户点「邮箱」Tab / 点文件夹 / 点「刷新」
        │
        ▼
MainWindow._on_mail_refresh(folder)
        │ 构造 imap_config（从 Settings 读取）
        ▼
MailFetchWorker(QThread)  ──后台──► IMAP 拉取该文件夹邮件
        │
        ├── 成功: emails_fetched(list) 信号
        │        │
        │        ▼
        │   MainWindow → MailCacheRepository.upsert_batch() 写入 mail_cache 表
        │        │
        │        ▼
        │   MailWidget 从 DB 加载邮件列表渲染
        │
        └── 失败: failed(reason) 信号 → 状态栏提示
```

### 缓存策略

每次拉取结果 upsert 到 `mail_cache`（按 folder + message_id 去重）。UI 打开邮箱时**先读缓存立即渲染**，同时触发后台刷新——秒开、不白屏。

### 读邮件流程

```
用户点击邮件列表某行
        │
        ▼
MailWidget 从 mail_cache 读 body_text → 阅读窗格显示
标记 is_read = 1
```

正文纯文本用 `QTextEdit` read-only 展示，HTML 留后续版本。

### 写信流程

```
用户点「写信」按钮
        │
        ▼
MailComposeDialog（QDialog）
  收件人 / 主题 / 正文（QTextEdit 纯文本）
        │ 点击发送
        ▼
MailSendWorker(QThread) ──后台──► SMTP 发送
        │
        ├── 成功 → 状态栏提示
        └── 失败 → 状态栏提示（对话框不关闭，可修改重试）
```

`MailSendWorker` 复用现有 `MailSender`（SMTP 发送逻辑已验证可用），但**不走 `MailComposer`**（那个是分身专用的，会拼聊天记录和作废授权尾注）。写信走标准 SMTP，发普通邮件。

## 线程模型

| Worker | 触发 | 信号 |
|--------|------|------|
| `MailFetchWorker` | 切换邮箱/文件夹/手动刷新 | `emails_fetched(list)`, `failed(str)` |
| `MailSendWorker` | 写信对话框点发送 | `sent()`, `failed(str)` |

两个 worker 都是短任务、用完即弃（不像 AIWorker 需要保留引用防 GC 崩溃）。

现有分身同步的两个 worker（`MailReceiveWorker` / `MailSendWorker` 分身专用）继续独立运行、不受影响。

## 错误处理

| 场景 | 处理 |
|------|------|
| IMAP 未配置 | 邮箱 Tab 可点，右侧显示空状态「请先在设置中配置 IMAP 邮箱」，带「打开设置」按钮 |
| 连接失败 | 状态栏提示，保留上次缓存的邮件列表仍可浏览 |
| 拉取中再次点刷新 | 上一个 worker 在跑则不重复触发 |
| SMTP 发送失败 | 状态栏提示失败原因，写信对话框不关闭 |
| 空收件箱 | 邮件列表显示空状态「收件箱是空的」 |

## 与现有分身同步的边界

| 关注点 | 分身同步（现有，不动） | 邮箱客户端（新增） |
|--------|----------------------|-------------------|
| 触发 | 后台定时器，按好友周期 | 用户手动刷新 |
| 收信 | `MailReceiveWorker` → 匹配 session → 插回聊天 | `MailFetchWorker` → 写 `mail_cache` 表 |
| 发信 | `MailComposer` 拼聊天记录 + 作废尾注 | `MailComposeDialog` 发普通邮件 |
| 数据表 | `processed_emails`（分身去重） | `mail_cache`（邮箱缓存） |
| 配置 | 同一套 SMTP/IMAP | 同一套 SMTP/IMAP |

**关键隔离：** 邮箱客户端拉取邮件只写 `mail_cache`，绝不插回聊天。两个系统共享连接参数，但操作的数据表和 UI 完全分开。

## 主题适配

- 全部新 Widget 走 `theme.current()` 取色，跟随现有深色/浅色即时切换
- 邮件阅读窗格用 `BG`/`FG` 配色
- 邮件列表选中项用 `ACCENT_SOFT`，与好友列表风格统一
- 写信对话框复用 `SettingsDialog` 的 QSS 风格模板（圆角输入框、accent 发送按钮）
- `VerticalTabBar` 选中项用 `ACCENT` 图标高亮，未选中用 `MUTED`

## 首版排除（不做）

- HTML 正文渲染
- 附件上传/下载
- 富文本编辑
- 多邮箱账号
- 邮件搜索
- 已发送/草稿文件夹的服务器同步
- 自动轮询（首版仅手动刷新）
