# ShadowTalk 邮箱 V1.4 增强设计

**日期**：2026-08-28
**状态**：已确认
**版本**：V1.4-Add（基于 V1.5-Add 邮箱基础功能之上）

## 概述

在 V1.5 邮箱基础功能（收+列+读+纯文本写信）之上，新增 4 项增强：

1. **HTML 正文渲染** — 安全沙箱化 QTextBrowser 显示 HTML 邮件
2. **附件** — 写信多附件、收信下载附件、大小限制、内联图片
3. **富文本编辑** — 写信工具栏支持格式/列表/链接/图片
4. **异步 SMTP 发送** — 后台线程发邮件不卡 UI

## 1. HTML 正文渲染

### 阅读窗格改造

`MailWidget` 的阅读窗格从 `QTextEdit` (read-only) 改为 `QTextBrowser`。

### 渲染逻辑

```
收到邮件 → 检查 content_type:
  ├── text/plain 存在 → 直接 setPlainText()（最安全）
  └── 只有 text/html → 安全过滤后 setHtml()
```

### 安全沙箱

- `QTextBrowser.setOpenExternalLinks(False)` — 禁止自动打开外链
- 自定义 `loadResource()` 或 `QTextDocument` 资源控制 — 禁止加载远程图片/CSS/字体
- HTML 过滤（用 BeautifulSoup 或正则）：
  - 删除 `<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, `<input>`
  - 删除所有 `on*` 事件处理器属性（onclick, onload, onerror 等）
  - 删除 `javascript:` 协议的链接
  - 保留内联 `style` 属性（可选剥离 `position:fixed/absolute` 等危险样式）
- 内联图片（`cid:xxx`）→ 从附件缓存加载本地文件路径替换后渲染

### HTML 过滤函数

新增 `core/html_sanitizer.py`（纯 Python，无 PySide6 依赖）：

```python
def sanitize_html(raw_html: str) -> str:
    """剥离危险标签和属性，返回安全 HTML。"""
    # 用 BeautifulSoup 解析
    # 白名单标签：p, br, div, span, b, i, u, s, strong, em, a, img, table, tr, td, th, ul, ol, li, h1-h6, blockquote, pre, code, font, big, small, sub, sup
    # 白名单属性：style（过滤后）, href, src, alt, title, width, height, align, colspan, rowspan, color, size, face
    # 删除 on* 事件属性
    # 删除 javascript: 链接
    # 删除 expression() 等危险 CSS
```

### 数据库

`mail_cache` 表新增两列：

```sql
ALTER TABLE mail_cache ADD COLUMN has_html INTEGER DEFAULT 0;
ALTER TABLE mail_cache ADD COLUMN has_attachments INTEGER DEFAULT 0;
```

**迁移**：在 `_migrate` 方法中用 `PRAGMA table_info(mail_cache)` 检查缺失列并 `ALTER TABLE ADD COLUMN`。

---

## 2. 附件

### 数据模型

**新增 `mail_attachments` 表**：

```sql
CREATE TABLE IF NOT EXISTS mail_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id INTEGER NOT NULL,        -- mail_cache.id
    filename TEXT NOT NULL,
    content_type TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    content_id TEXT DEFAULT '',        -- 内联图片的 CID
    is_inline INTEGER DEFAULT 0,      -- 是否为内联图片
    saved_path TEXT DEFAULT '',        -- 本地缓存路径
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (email_id) REFERENCES mail_cache(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mail_att_email ON mail_attachments(email_id);
```

**附件存储目录**：`~/.shadowtalk/mail_attachments/<email_id>/`

### 收信下载附件

**MailReceiver 改造**：
- 新增 `extract_attachments(msg)` 函数：遍历 `msg.walk()`
- 跳过 multipart 容器 part
- 每个附件 part 提取：filename（`get_filename()`）、content_type、content_disposition（attachment/inline）、content_id（`get('Content-ID')`）、payload（`get_payload(decode=True)`）
- 返回 `list[dict]`

**MailFetchWorker 改造**：
- 拉取邮件后调用 `extract_attachments()`
- 每个邮件的附件列表写入 `mail_attachments` 表（保存到本地缓存目录）
- 返回的邮件 dict 新增 `attachments` 键

**MailCacheRepository 扩展**：
- 新增 `save_attachments(email_id, attachments)` — 批量写入附件表
- 新增 `get_attachments(email_id)` — 查询某邮件的附件列表

**MailWidget 阅读窗格**：
- 底部新增附件栏（QFrame）
- 每个附件显示：📄 图标 + 文件名 + 大小 + 保存按钮
- 点击保存 → `QFileDialog.getSaveFileName()` → 复制 local 文件到用户选择路径
- 内联图片不显示在附件栏（已嵌入 HTML）

**大小限制**：
- 单附件 ≤ 10MB
- 总附件 ≤ 25MB
- 超限附件显示 "（过大，无法下载）"

### 写信添加附件

**MailComposeDialog 改造**：
- 正文区上方新增附件栏：已添加附件列表 + "📎 添加附件" 按钮
- 点击添加 → `QFileDialog.getOpenFileNames()`（多选）
- 每个附件显示：文件名 + 大小 + 移除按钮（✕）
- 发送时构建 `MIMEMultipart(mixed)`：
  - 正文部分：`MIMEMultipart(alternative)` 包含 text/plain + text/html
  - 每个附件：`MIMEApplication(data, Name=filename)` + `Content-Disposition: attachment; filename="xxx"`

### 内联图片

- 收信时：有 `Content-ID` 头的 part 标记 `is_inline=1`，保存到本地
- HTML 渲染时：`cid:xxx` 替换为 `file:///<local_path>`
- 写信时：插入图片 → 自动生成 CID（如 `image001@shadowtalk.local`）→ 作为 `MIMEImage` + `Content-ID: <cid>` 头 → HTML 正文中 `<img src="cid:image001@shadowtalk.local">`

---

## 3. 富文本编辑

### MailComposeDialog 改造

**正文区**：保持 `QTextEdit`（默认支持富文本），`setAcceptRichText(True)`。

**新增格式工具栏**（正文区上方，高度 ~40px）：

```
[B] [I] [U] [S]  |  [H▼]标题  |  [🎨]颜色  |  [•]无序  |  [1.]有序  |  [🔗]链接  |  [🖼️]图片
```

### 实现方式

| 功能 | 实现 |
|------|------|
| **加粗** | `QTextCharFormat.setFontWeight(Bold)` → `cursor.mergeCharFormat()`，toggle 逻辑 |
| **斜体** | `QTextCharFormat.setFontItalic(True/False)` |
| **下划线** | `QTextCharFormat.setFontUnderline(True/False)` |
| **删除线** | `QTextCharFormat.setFontStrikeOut(True/False)` |
| **字体大小** | `QTextCharFormat.setFontPointSize()` + 下拉框（9/10/12/14/16/18/24） |
| **字体颜色** | `QTextCharFormat.setForeground(QColor)` → `QColorDialog.getColor()` |
| **标题 H1-H3** | `QTextBlockFormat` + `setTextIndent`/`setTopMargin` 模拟，或字体大小 |
| **无序列表** | `QTextListFormat.Style.ListDisc` → `cursor.insertList()` |
| **有序列表** | `QTextListFormat.Style.ListDecimal` |
| **插入链接** | `QInputDialog` 输入 URL → `QTextCharFormat.setAnchorHref(url)` + `setAnchor(True)` + 设置蓝色下划线 |
| **插入图片** | `QFileDialog` 选图片 → 生成 CID → `cursor.insertImage()` 或自定义资源 |

### 工具栏状态同步

- `cursorPositionChanged` 信号 → `update_toolbar_state()`
- 读取当前 `textCursor().charFormat()` 更新按钮选中状态
- 实现 `_toggle_format()` 通用 toggle 方法

### 发送逻辑

```python
html_body = body_edit.toHtml()       # 富文本 → HTML（Qt 生成）
plain_body = body_edit.toPlainText()  # 纯文本 fallback

# 构建 MIMEMultipart(alternative)
#   ├── text/plain (plain_body)
#   └── text/html (html_body)       # Qt 生成的 HTML 含内联图片引用
```

---

## 4. 异步 SMTP 发送

### 新建 MailComposeSendWorker

**文件**：`shadowtalk/ui/threads/mail_compose_send_worker.py`

```python
class MailComposeSendWorker(QThread):
    """通用邮件发送线程（独立于分身同步的 MailSendWorker）。"""

    sent = Signal()              # 发送成功
    failed = Signal(str)         # 失败原因

    def __init__(self, mail_msg: MailMessage, mail_config: dict, parent=None):
        super().__init__(parent)
        self.mail_msg = mail_msg
        self.mail_config = mail_config
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            sender = MailSender(
                smtp_host=self.mail_config["host"],
                smtp_port=int(self.mail_config["port"]),
                use_tls=self.mail_config.get("use_tls", True),
                username=self.mail_config.get("username", ""),
                password=self.mail_config.get("password", ""),
            )
            sender.send(self.mail_msg)
            if not self._cancelled:
                self.sent.emit()
        except Exception as e:
            logger.error("邮件发送失败：%s", e)
            if not self._cancelled:
                self.failed.emit(str(e))
```

### MainWindow 改造

`_on_send_mail()` 不再同步调用 `MailSender`：

1. 构建 `MailMessage`（含附件 MIME 部分）
2. 创建 `MailComposeSendWorker`
3. 发送中：禁用发送按钮 + 状态栏 "正在发送…"
4. `worker.sent.connect()` → 状态栏 "邮件已发送" + 关闭对话框
5. `worker.failed.connect()` → 状态栏提示 + 保持对话框打开

---

## 新增文件清单

| 文件 | 职责 |
|------|------|
| `core/html_sanitizer.py` | HTML 安全过滤（纯 Python） |
| `ui/threads/mail_compose_send_worker.py` | 异步 SMTP 发送线程 |

## 修改文件清单

| 文件 | 变更 |
|------|------|
| `core/mail_receiver.py` | 新增 `extract_attachments()` |
| `ui/threads/mail_fetch_worker.py` | 返回附件数据 |
| `ui/widgets/mail_widget.py` | QTextBrowser + 附件栏 |
| `ui/widgets/mail_compose_dialog.py` | 工具栏 + 附件栏 + 富文本 |
| `ui/widgets/vertical_tab_bar.py` | 无变更 |
| `data/database.py` | 新增 mail_attachments 表 + mail_cache 新列 |
| `data/repositories.py` | MailCacheRepository 扩展附件方法 |
| `ui/main_window.py` | _on_send_mail 改为异步 |

## 新增测试

| 文件 | 测试内容 |
|------|----------|
| `tests/test_html_sanitizer.py` | HTML 过滤（剥离 script/事件/危险标签） |
| `tests/test_mail_compose_send_worker.py` | 异步发送（mock SMTP） |
| `tests/test_mail_attachments.py` | 附件提取 + 保存 + 查询 |

## 全局约束

- Python 3.11+, PySide6
- core/ 和 data/ 禁止 import PySide6 或 ui/
- BeautifulSoup 已在 requirements.txt（用于 HTML 过滤）
- 中文注释解释"why"
- 用户-facing 字符串用中文
- 现有 V1.5 功能（纯文本收发、搜索联系人等）继续正常工作
