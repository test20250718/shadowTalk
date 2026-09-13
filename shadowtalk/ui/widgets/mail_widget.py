# shadowtalk/ui/widgets/mail_widget.py
"""
ShadowTalk 邮箱主面板：邮件列表（左）+ 阅读窗格（右）。

设计要点：
- 顶部工具栏（写信=主操作高亮 + 刷新/回复/删除/联系人=次级按钮）+ 水平 QSplitter
- 邮件列表项为自定义 _EmailListItem（头像 + 发件人 + 主题 + 正文预览 + 时间）
- 阅读窗格用 HTML 渲染信头卡片 + 正文（告别纯文本拼接，视觉层级清晰）
- 空状态提示（收件箱为空时引导用户）
- 数据来自 MailCacheRepository（缓存），不直接访问网络
- 提供 load_folder(folder) 供 MainWindow 切换文件夹
- 提供 restyle() 供主题切换时刷新样式
- refresh_requested 信号通知 MainWindow 执行后台拉取
"""
import html
import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QFont

from shadowtalk.ui.theme import current as theme_current
from shadowtalk.ui.widgets.message_bubble import AvatarLabel
from shadowtalk.data.repositories import MailCacheRepository, MailContactRepository
from shadowtalk.config.i18n import tr, on_language_changed


# ── 邮件 HTML 净化（白名单式剔除，防御纵深）──
# QTextBrowser 本身不执行 JS 且已禁用外链/远程图片，这里再剔除
# script/style/iframe 等块与 on* 事件、javascript: 协议，防止渲染杂讯
_SCRIPT_BLOCK_RE = re.compile(
    r"<(script|style|iframe|object|embed|form)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL)
_EVENT_ATTR_RE = re.compile(
    r'\son\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)
_JS_URL_RE = re.compile(
    r'(href|src)\s*=\s*(["\']?)\s*javascript:[^"\'>\s]*', re.IGNORECASE)
# 宽度属性（像素值）：邮件 HTML 常带 width="700" 的表格（GitLab 日报），
# 超过窗格宽度的按原宽渲染会撑大阅读窗格、挤压列表 → 收敛为 100% 自适应；
# 百分比宽度（外层 width="100%" 是居中结构的容器）与小宽度（间距单元格）保留
_WIDTH_ATTR_RE = re.compile(
    r'\swidth\s*=\s*("(\d+)(px)?"|\'(\d+)(px)?\'|\d+px)', re.IGNORECASE)
# 表格居中注入：Qt 富文本引擎里 <td align="center"> 只对文字生效，
# 嵌套表格是块级元素必须用 <table align="center">（QTextTableFormat 对齐）
# 才能居中——邮件自带的 td align=center 布局在网页有效、在 Qt 无效，
# 统一给无 align 属性的表格注入居中（100% 宽表格居中无视觉变化）
_TABLE_TAG_RE = re.compile(r'<table\b(?![^>]*\balign\s*=)', re.IGNORECASE)


def _download_image_b64(url: str, timeout: float = 3.0) -> str | None:
    """下载远程图片并返回 base64 data URI（失败返回 None）。"""
    try:
        import urllib.request
        import base64
        import mimetypes
        # 跳过跟踪像素（1x1 小图）
        low = url.lower()
        if "track" in low or "open2" in low or "pixel" in low:
            return None
        req = urllib.request.Request(url, headers={
            "User-Agent": "ShadowTalk/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            guess = mimetypes.guess_type(url)[0]
            ctype = guess if guess else "image/png"
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception:
        return None


def _image_dimensions(b64_uri: str) -> tuple[int, int]:
    """解析 base64 data URI 图片的自然尺寸（失败返回 (0, 0)）。"""
    try:
        import base64
        from PySide6.QtGui import QImage
        raw = base64.b64decode(b64_uri.split(",", 1)[1])
        img = QImage.fromData(raw)
        return img.width(), img.height()
    except Exception:
        return 0, 0


def _rewrite_img_tag(html: str, url: str, b64: str,
                     max_w: int = 640) -> str:
    """把引用远程 URL 的整个 img 标签重写为内嵌 base64 的干净标签。

    邮件 HTML 的 img 常带 height="auto" 这类非法属性（HTML 宽高属性
    只接受数字），Qt 富文本引擎解析失败后布局高度按 0 计算，图片
    渲染出来了但文字不换行、直接叠在图上（用户报告：logo 与文字
    重叠）。按图片真实纵横比写显式 width/height 才能撑出正确布局。
    """
    pattern = re.compile(
        r'<img\b[^>]*\bsrc\s*=\s*["\']' + re.escape(url) + r'["\'][^>]*>',
        re.IGNORECASE)
    m = pattern.search(html)
    if not m:
        # 找不到完整标签（异常 HTML）：退化为只换 src 值
        return html.replace(f'src="{url}"', f'src="{b64}"').replace(
            f"src='{url}'", f'src="{b64}"')
    tag = m.group(0)
    w, h = _image_dimensions(b64)
    if not w or not h:
        return html.replace(tag, f'<img src="{b64}">')
    # 宽度：优先沿用邮件里声明的像素宽，无则用上限宽
    wm = re.search(r'\bwidth\s*=\s*["\']?(\d+)', tag, re.IGNORECASE)
    target_w = min(int(wm.group(1)), max_w) if wm else max_w
    target_h = round(target_w * h / w)
    return html.replace(
        tag, f'<img src="{b64}" width="{target_w}" height="{target_h}">')


def _sanitize_email_html(raw_html: str, max_width: int = 0,
                         fill_px: int = 0, download_images: bool = True) -> str:
    """净化邮件 HTML 正文。

    - 剔除脚本/事件/js 协议（防御纵深）
    - 宽度处理（Qt 嵌套表格不吃百分比宽度，width="100%" 的外层表格
      会缩到内容宽导致内容挤在左侧）：
      * 像素宽度超过 max_width → 收敛为 fill_px（卡片宽，防撑爆窗格）
      * 表格的 width="100%" → fill_px（真正撑满居中容器）
      * 小宽度（间距单元格等）保留
    - 无 align 属性的表格注入 align="center"（Qt 块级表格居中
      必须用 table 自身的 align，td align=center 只对文字生效）
    """
    cleaned = _SCRIPT_BLOCK_RE.sub("", raw_html or "")
    cleaned = _EVENT_ATTR_RE.sub("", cleaned)
    cleaned = _JS_URL_RE.sub(r"\1=\2#", cleaned)

    fallback = f' width="{fill_px}"' if fill_px else ' width="100%"'

    def _cap_width(match):
        val = match.group(2) or match.group(4) or ""
        try:
            n = int(val)
        except (ValueError, TypeError):
            return match.group(0)
        if max_width and n > max_width:
            return fallback
        return match.group(0)

    cleaned = _WIDTH_ATTR_RE.sub(_cap_width, cleaned)
    # 表格的 100% 宽 → 卡片像素宽（Qt 不支持嵌套表格百分比宽度）
    if fill_px:
        cleaned = re.sub(
            r'(<table\b[^>]*?)\swidth\s*=\s*("100%"|\'100%\')',
            rf'\1 width="{fill_px}"', cleaned, flags=re.IGNORECASE)
    # 表格默认居中（网页邮件的卡片式布局惯例）
    cleaned = _TABLE_TAG_RE.sub('<table align="center"', cleaned)
    # 深色模式：直接替换邮件 HTML 中的背景色/文字色（Qt HTML 引擎不尊重 !important）
    t = theme_current()
    # 替换所有 background-color / background 的浅色值为透明（让外层暗色背景透过来）
    def _replace_bg(m):
        prefix = m.group(1)  # "background-color:" 或 "background:"
        val = m.group(2).strip().rstrip(";")
        # 只把接近白色的背景换成透明，保留有彩色（如按钮蓝）
        if re.match(r'#f{3,6}$', val, re.IGNORECASE) or val.lower() in (
                '#ffffff', '#f6f7fa', '#f5f5f5', '#fafafa', '#f0f0f0',
                '#f8f8f8', '#fbfbfb', '#eeeeee', '#e0e0e0'):
            return prefix + 'transparent'
        return m.group(0)
    cleaned = re.sub(
        r'(background(?:-color)?\s*:\s*)(#[0-9a-fA-F]{3,8}|[a-z]+)',
        _replace_bg, cleaned, flags=re.IGNORECASE)
    # 同时替换 bgcolor 属性
    def _replace_bgcolor_attr(m):
        val = m.group(1).strip()
        if re.match(r'#f{3,6}$', val, re.IGNORECASE) or val.lower() in (
                '#ffffff', '#f6f7fa', '#f5f5f5', '#fafafa'):
            return 'bgcolor="transparent"'
        return m.group(0)
    cleaned = re.sub(
        r'bgcolor\s*=\s*["\']?(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)["\']?',
        _replace_bgcolor_attr, cleaned, flags=re.IGNORECASE)
    # 深色模式：替换邮件自带深色文字为前景色（暗色背景上深字看不清）
    def _replace_text_color(m):
        prefix = m.group(1)  # "color:" 或 "color :"
        val = m.group(2).strip().rstrip(";")
        # 把深色文字（亮度低）换成前景色，保留有彩色（蓝、绿等）和浅色
        lower = val.lower()
        if lower in ('#020e36', '#262626', '#37352f', '#222222', '#333333',
                     '#444444', '#111111', '#000000', 'black'):
            return prefix + t.FG
        # 匹配 #RRGGBB 中 R/G/B 均 ≤ 0x44 的深暗色
        m2 = re.match(r'#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$', val)
        if m2:
            r, g, b = int(m2.group(1), 16), int(m2.group(2), 16), int(m2.group(3), 16)
            if r <= 0x44 and g <= 0x44 and b <= 0x44:
                return prefix + t.FG
        return m.group(0)
    # 只匹配 "color:" 不匹配 "background-color:"（前面已处理背景）
    cleaned = re.sub(
        r'(?<!-)(color\s*:\s*)(#[0-9a-fA-F]{3,8}|[a-z]+)',
        _replace_text_color, cleaned, flags=re.IGNORECASE)
    # 同时处理 rgba/rgb 格式的深色文字
    def _replace_rgba_color(m):
        prefix = m.group(1)
        r, g, b = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if r <= 0x44 and g <= 0x44 and b <= 0x44:
            return prefix + t.FG
        return m.group(0)
    cleaned = re.sub(
        r'(?<!-)(color\s*:\s*)rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)',
        _replace_rgba_color, cleaned, flags=re.IGNORECASE)
    # 剔除非法的 height="auto" 属性（HTML 宽高属性只接受数字，
    # Qt 解析失败按 0 高布局 → 图片与下方文字重叠）
    cleaned = re.sub(r'\s+height\s*=\s*["\']?auto["\']?', '', cleaned,
                     flags=re.IGNORECASE)
    # 远程图片处理
    if download_images:
        # 同步下载并内嵌为 base64（会阻塞，但确保图片显示）
        def _replace_img_src(m):
            quote = m.group(1)   # '"' 或 "'"
            url = m.group(2).strip()
            if not url.startswith(("http://", "https://")):
                return m.group(0)
            b64 = _download_image_b64(url)
            if b64:
                return f'src={quote}{b64}{quote}'
            return m.group(0)
        cleaned = re.sub(
            r'src\s*=\s*(["\'])([^"\']+)\1',
            _replace_img_src, cleaned, flags=re.IGNORECASE)
    # else: 不下载图片，保留原 URL（Qt 不加载远程资源，但正文不阻塞）
    return cleaned


class _EmailListItem(QWidget):
    """邮件列表项：圆形头像 + 发件人 + 主题 + 正文预览 + 时间。

    未读邮件用：主题色小圆点 + 加粗发件人/主题 + 背景淡色高亮，
    已读则常规字重 + 透明背景。三行布局信息密度更高。
    """

    def __init__(self, email: dict, parent=None):
        super().__init__(parent)
        self._email = email
        self._is_read = bool(email.get("is_read", 0))
        self._build_ui()

    def _build_ui(self):
        # ── 根布局：左侧竖条（未读高亮）+ 内容区 ──
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 12, 0)
        root.setSpacing(10)

        # 未读高亮条：3px 宽竖条，仅未读时显示（Outlook/Apple Mail 风格）
        self._unread_bar = QFrame()
        self._unread_bar.setFixedWidth(3)
        self._unread_bar.setVisible(not self._is_read)
        root.addWidget(self._unread_bar)

        # ── 头像 ──
        sender = self._email.get("sender", "") or "?"
        avatar = AvatarLabel(sender, "", size=40, variant="soft")
        root.addWidget(avatar)

        # ── 中部：发件人 + 主题 + 正文预览 ──
        center = QVBoxLayout()
        center.setSpacing(2)
        center.setContentsMargins(0, 4, 0, 4)

        # 第一行：发件人
        name_label = QLabel(sender)
        name_label.setObjectName("emailSender")
        if not self._is_read:
            font = name_label.font()
            font.setBold(True)
            name_label.setFont(font)
        center.addWidget(name_label)

        # 第二行：主题
        subject = self._email.get("subject", "") or "(无主题)"
        subject_label = QLabel(subject)
        subject_label.setObjectName("emailSubject")
        subject_label.setWordWrap(False)
        if not self._is_read:
            font = subject_label.font()
            font.setBold(True)
            subject_label.setFont(font)
        center.addWidget(subject_label)

        # 第三行：正文预览（新增，提升信息密度）
        body_preview = (self._email.get("body_text", "") or "").strip()
        # 取前 80 字符，去除多余空白
        body_preview = " ".join(body_preview.split())[:80]
        if body_preview:
            preview_label = QLabel(body_preview)
            preview_label.setObjectName("emailPreview")
            preview_label.setWordWrap(False)
            center.addWidget(preview_label)

        center.addStretch()  # 无预览时内容靠上
        root.addLayout(center, 1)

        # ── 右侧：时间 ──
        right = QVBoxLayout()
        right.setSpacing(2)
        right.setContentsMargins(0, 0, 0, 0)
        right.setAlignment(Qt.AlignRight | Qt.AlignTop)

        received = self._email.get("received_at", "") or ""
        # 只显示日期部分（YYYY-MM-DD），节省横向空间
        date_str = received[:10] if received else ""
        time_label = QLabel(date_str)
        time_label.setObjectName("emailTime")
        right.addWidget(time_label)
        right.addStretch()

        root.addLayout(right)

    def apply_style(self):
        """主题切换时刷新文字颜色。"""
        t = theme_current()
        # 未读高亮条
        if self._unread_bar.isVisible():
            self._unread_bar.setStyleSheet(
                f"background-color: {t.ACCENT}; border-radius: 2px;")
        else:
            self._unread_bar.setStyleSheet("background-color: transparent;")
        # 文字
        for label in self.findChildren(QLabel):
            if label.objectName() == "emailSender":
                label.setStyleSheet(f"color: {t.FG}; font-size: 13px;")
            elif label.objectName() == "emailSubject":
                label.setStyleSheet(f"color: {t.FG}; font-size: 13px;")
            elif label.objectName() == "emailPreview":
                label.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
            elif label.objectName() == "emailTime":
                label.setStyleSheet(f"color: {t.MUTED}; font-size: 11px;")


class MailWidget(QWidget):
    """邮箱主面板：邮件列表 + 阅读窗格。"""

    refresh_requested = Signal()  # 通知 MainWindow 执行后台拉取
    reply_requested = Signal()    # 回复当前选中邮件
    delete_requested = Signal()   # 删除当前选中邮件
    contacts_requested = Signal() # 切换到联系人管理视图
    # 远程图片下载完成（携带完整 HTML + 邮件 id）。
    # 后台线程通过 emit 跨线程投递（queued connection 回主线程）——
    # QTimer.singleShot 不能在无事件循环的后台线程用，定时器永不触发
    # （用户报告：邮件正文图片永远不显示）。
    images_ready = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_folder = "INBOX"
        self._selected_email = None   # 当前选中邮件 dict（回复/删除目标）
        self._last_render_width = 0   # 上次渲染 HTML 正文时的窗格宽度
        self._build_ui()
        # 图片下载完成信号：跨线程投递回主线程更新阅读窗格
        self.images_ready.connect(self._on_images_ready)
        # 语言切换时刷新工具栏按钮文本
        on_language_changed(self._retranslate_toolbar)
        # 阅读窗格宽度变化 → 防抖后按新宽度重渲染 HTML 正文
        #（宽度收敛阈值依赖窗格宽度，拖动分割条/改窗口后保持布局正确）
        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.setInterval(400)
        self._rerender_timer.timeout.connect(self._rerender_for_width)
        self.reading_pane.viewport().installEventFilter(self)

    def _retranslate_toolbar(self):
        """语言切换后刷新工具栏按钮文本。"""
        self.compose_btn.setText("✉️ " + tr("写信"))
        self.refresh_btn.setText("🔄 " + tr("刷新"))
        self.reply_btn.setText("↩️ " + tr("回复"))
        self.delete_btn.setText("🗑️ " + tr("删除"))
        self.contacts_btn.setText("👥 " + tr("联系人"))

    @property
    def current_folder(self) -> str:
        """当前正在显示的文件夹名（供 MainWindow 刷新时对齐）。"""
        return self._current_folder

    @property
    def selected_email(self) -> dict | None:
        """当前选中的邮件（None 表示未选中）。多选时返回第一个。"""
        return self._selected_email

    @property
    def selected_emails(self) -> list[dict]:
        """所有选中的邮件列表（多选删除用）。"""
        emails = []
        for item in self.email_list.selectedItems():
            email_id = item.data(Qt.UserRole)
            email = MailCacheRepository.get_by_id(email_id)
            if email:
                emails.append(email)
        return emails

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 顶部工具栏 ──
        toolbar = QFrame()
        toolbar.setObjectName("mailToolbar")
        toolbar.setFixedHeight(52)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(16, 0, 12, 0)
        tb_layout.setSpacing(8)

        # 写信按钮（主操作：Accent 高亮）
        self.compose_btn = QPushButton("✉️ " + tr("写信"))
        self.compose_btn.setObjectName("mailComposeBtn")
        self.compose_btn.setCursor(Qt.PointingHandCursor)
        tb_layout.addWidget(self.compose_btn)

        # 刷新按钮（次级：幽灵风格）
        self.refresh_btn = QPushButton("🔄 " + tr("刷新"))
        self.refresh_btn.setObjectName("mailRefreshBtn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self._on_refresh)
        tb_layout.addWidget(self.refresh_btn)

        # 回复按钮（需先选中邮件）
        self.reply_btn = QPushButton("↩️ " + tr("回复"))
        self.reply_btn.setObjectName("mailReplyBtn")
        self.reply_btn.setCursor(Qt.PointingHandCursor)
        self.reply_btn.setEnabled(False)
        self.reply_btn.clicked.connect(self._on_reply)
        tb_layout.addWidget(self.reply_btn)

        # 删除按钮（需先选中邮件）
        self.delete_btn = QPushButton("🗑️ " + tr("删除"))
        self.delete_btn.setObjectName("mailDeleteBtn")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete)
        tb_layout.addWidget(self.delete_btn)

        # 联系人按钮
        self.contacts_btn = QPushButton("👥 " + tr("联系人"))
        self.contacts_btn.setObjectName("mailContactsBtn")
        self.contacts_btn.setCursor(Qt.PointingHandCursor)
        self.contacts_btn.clicked.connect(
            lambda: self.contacts_requested.emit())
        tb_layout.addWidget(self.contacts_btn)

        # 选择计数标签（多选时显示 "已选 N 封"）
        self._selection_label = QLabel("")
        self._selection_label.setObjectName("mailSelectionLabel")
        tb_layout.addWidget(self._selection_label)

        tb_layout.addStretch()

        # 文件夹标签
        self.folder_label = QLabel("📥 收件箱")
        self.folder_label.setObjectName("mailFolderLabel")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.folder_label.setFont(font)
        tb_layout.addWidget(self.folder_label)

        layout.addWidget(toolbar)

        # ── 水平分割：邮件列表 + 阅读窗格 ──
        splitter = QSplitter(Qt.Horizontal)

        # 左侧邮件列表（外层包一个 QWidget 放空状态）
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self.email_list = QListWidget()
        self.email_list.setObjectName("mailList")
        self.email_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 多选模式：支持 Ctrl+点选、Shift+连选、拖拽框选（与 Outlook 一致）
        self.email_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.email_list.itemClicked.connect(self._on_email_clicked)
        # 选择变化时更新按钮状态 + 计数标签
        self.email_list.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.email_list, 1)

        # 空状态提示（列表为空时显示）
        self._empty_label = QLabel("📭 收件箱空空如也\n\n写封信或点击刷新来收取邮件")
        self._empty_label.setObjectName("mailEmptyLabel")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setVisible(False)
        list_layout.addWidget(self._empty_label, 1)

        splitter.addWidget(list_container)

        # 右侧阅读窗格（QTextBrowser 提供安全沙箱化 HTML 渲染）
        self.reading_pane = QTextBrowser()
        self.reading_pane.setObjectName("mailReadingPane")
        self.reading_pane.setOpenExternalLinks(False)
        self.reading_pane.setOpenLinks(False)
        self.reading_pane.setReadOnly(True)
        self.reading_pane.setPlaceholderText(tr("选择一封邮件阅读"))
        # 远程图片通过 _sanitize_email_html 下载并内嵌为 base64 显示

        # 右侧面板：阅读窗格 + 附件栏（垂直布局）
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.reading_pane, 1)
        # 附件栏初始为空，点击邮件后由 _show_attachments 填充
        self._attachment_bar = None
        splitter.addWidget(right_panel)

        # 初始比例 4:6（列表稍窄）
        splitter.setSizes([400, 600])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._apply_styles()

    def _apply_styles(self):
        """应用当前主题样式。"""
        t = theme_current()
        # 工具栏
        self.setStyleSheet(f"background-color: {t.BG};")
        for frame in self.findChildren(QFrame):
            if frame.objectName() == "mailToolbar":
                frame.setStyleSheet(
                    f"background-color: {t.SURFACE}; "
                    f"border-bottom: 1px solid {t.BORDER};"
                )

        # ── 主操作按钮（写信）：Accent 高亮 ──
        compose_style = (
            f"QPushButton{{"
            f"background-color: {t.ACCENT}; "
            f"color: white; "
            f"border: none; "
            f"border-radius: 6px; "
            f"padding: 5px 16px; "
            f"font-size: 13px; "
            f"font-weight: bold;"
            f"}}"
            f"QPushButton:hover{{"
            f"background-color: {t.ACCENT_HOVER};"
            f"}}"
            f"QPushButton:pressed{{"
            f"background-color: {t.ACCENT_PRESSED};"
            f"}}"
        )
        self.compose_btn.setStyleSheet(compose_style)

        # ── 次级按钮（刷新/回复/删除/联系人）：幽灵风格 ──
        ghost_style = (
            f"QPushButton{{"
            f"background-color: transparent; "
            f"color: {t.FG}; "
            f"border: 1px solid {t.BORDER}; "
            f"border-radius: 6px; "
            f"padding: 4px 12px; "
            f"font-size: 13px;"
            f"}}"
            f"QPushButton:hover{{"
            f"background-color: {t.SURFACE}; "
            f"border-color: {t.MUTED};"
            f"}}"
            f"QPushButton:disabled{{"
            f"color: {t.BORDER};"
            f"}}"
        )
        self.refresh_btn.setStyleSheet(ghost_style)
        self.reply_btn.setStyleSheet(ghost_style)
        self.delete_btn.setStyleSheet(ghost_style)
        self.contacts_btn.setStyleSheet(ghost_style)

        # 文件夹标签
        self.folder_label.setStyleSheet(f"color: {t.FG};")

        # 选择计数标签
        self._selection_label.setStyleSheet(
            f"color: {t.ACCENT}; font-size: 13px; font-weight: bold;")

        # 邮件列表
        self.email_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {t.SURFACE};
                border: none;
                outline: none;
                padding: 4px 0;
            }}
            QListWidget::item {{
                background-color: transparent;
                border: none;
                border-bottom: 1px solid {t.BORDER};
            }}
            QListWidget::item:hover {{
                background-color: {t.BG};
            }}
            QListWidget::item:selected {{
                background-color: {t.ACCENT_SOFT};
            }}
        """)

        # 空状态标签
        self._empty_label.setStyleSheet(
            f"color: {t.MUTED}; font-size: 14px; line-height: 1.8;")

        # 阅读窗格（QTextBrowser）
        self.reading_pane.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: none;
                padding: 16px 20px;
                font-size: 14px;
                line-height: 1.6;
            }}
        """)

        # 附件栏样式（存在时）
        if self._attachment_bar:
            self._attachment_bar.setStyleSheet(
                f"background-color: {t.SURFACE}; "
                f"border-top: 1px solid {t.BORDER};"
            )
            for btn in self._attachment_bar.findChildren(QPushButton):
                btn.setStyleSheet(
                    f"QPushButton{{"
                    f"background-color: {t.BG}; "
                    f"color: {t.FG}; "
                    f"border: 1px solid {t.BORDER}; "
                    f"border-radius: 6px; "
                    f"padding: 4px 12px; "
                    f"font-size: 12px;"
                    f"}}"
                    f"QPushButton:hover{{"
                    f"background-color: {t.ACCENT_SOFT}; "
                    f"border-color: {t.ACCENT};"
                    f"}}"
                )

        # 刷新列表项样式
        for i in range(self.email_list.count()):
            item = self.email_list.item(i)
            widget = self.email_list.itemWidget(item)
            if isinstance(widget, _EmailListItem):
                widget.apply_style()

    def restyle(self):
        """主题切换后由 MainWindow 调用。"""
        self._apply_styles()
        # 同步刷新工具栏按钮文本（语言切换后）
        self.compose_btn.setText("✉️ " + tr("写信"))
        self.refresh_btn.setText("🔄 " + tr("刷新"))
        self.reply_btn.setText("↩️ " + tr("回复"))
        self.delete_btn.setText("🗑️ " + tr("删除"))
        self.contacts_btn.setText("👥 " + tr("联系人"))
        # 重渲染当前阅读的邮件：净化时按主题把颜色烘焙进了 HTML
        # （暗色模式把深色文字换成浅色、白底改透明），切换主题后
        # 旧 HTML 的颜色不再匹配新主题——浅色模式下浅色字配白底
        # 完全看不清（用户报告）。重渲染让颜色按新主题重新计算。
        if self._selected_email:
            self._render_reading_pane(self._selected_email)

    @staticmethod
    def _apply_contact_names(email: dict, name_map: dict) -> dict:
        """把裸发件人地址换成联系人显示名（用户命名的名字优先）。

        很多邮件头不带显示名（sender 即地址），用户在联系人页命名后
        邮件列表应显示名字。返回浅拷贝，不改动缓存 dict 原值。
        """
        cname = name_map.get((email.get("sender_addr") or "").strip())
        if cname:
            e = dict(email)
            e["sender"] = cname
            return e
        return email

    def eventFilter(self, obj, event):
        """监听阅读窗格尺寸变化 → 防抖重渲染 HTML 正文。"""
        if (obj is self.reading_pane.viewport()
                and event.type() == QEvent.Resize):
            self._rerender_timer.start()
        return super().eventFilter(obj, event)

    def _rerender_for_width(self):
        """窗格宽度变化后按新宽度重渲染当前邮件（仅 HTML 正文，且宽度显著变化）。

        宽度收敛（超宽表格→100%）依赖渲染时的窗格宽度；拖动分割条或
        改窗口大小后重渲染保持布局正确。重渲染后恢复滚动位置。
        """
        email = self._selected_email
        if not email or not (email.get("body_html", "") or "").strip():
            return
        new_width = self.reading_pane.viewport().width()
        # 宽度变化不显著（<40px）不重渲染，避免频繁闪烁
        if abs(new_width - (self._last_render_width or 0)) < 40:
            return
        scrollbar = self.reading_pane.verticalScrollBar()
        saved_pos = scrollbar.value()
        self._render_reading_pane(email)
        scrollbar.setValue(saved_pos)

    def load_folder(self, folder: str):
        """加载指定文件夹的邮件列表。

        从 MailCacheRepository 读取缓存，清空并重新渲染列表。
        自动刷新不应打断阅读：若之前选中的邮件仍在新的列表里，
        恢复其选中状态并保留阅读窗格内容（用户报告：正在看邮件，
        自动刷新"收到 N 封"提示后正文被清空）。
        """
        self._current_folder = folder
        # 更新文件夹标签（简单映射，后续可扩展）
        folder_display = {
            "INBOX": "📥 收件箱",
            "Sent": "📤 已发送",
            "Drafts": "📝 草稿",
            "Trash": "🗑️ 垃圾箱",
        }.get(folder, folder)
        self.folder_label.setText(folder_display)

        # 记录当前选中（刷新后若该邮件仍在列表中则恢复）
        prev_selected_id = None
        if self._selected_email:
            prev_selected_id = self._selected_email.get("id")

        # 清空列表 + 选中状态（阅读窗格/附件栏是否清空见下方恢复逻辑）
        self.email_list.clear()
        self._selected_email = None
        self.reply_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self._selection_label.setText("")

        # 从缓存读取（最新 200 条，防超长列表卡顿）
        emails = MailCacheRepository.get_by_folder(folder, limit=200)
        # 联系人名字映射：有名字的发件人显示名字而非裸地址
        name_map = MailContactRepository.get_name_map()

        # 空状态切换
        self._empty_label.setVisible(len(emails) == 0)
        self.email_list.setVisible(len(emails) > 0)

        restored = False
        for email in emails:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, email["id"])
            item.setSizeHint(QSize(0, 76))  # 三行布局，稍高
            self.email_list.addItem(item)
            widget = _EmailListItem(self._apply_contact_names(email, name_map))
            widget.apply_style()
            self.email_list.setItemWidget(item, widget)
            # 恢复之前选中的邮件（blockSignals 避免触发选择变化回调）
            if prev_selected_id is not None and email["id"] == prev_selected_id:
                self.email_list.blockSignals(True)
                self.email_list.setCurrentItem(item)
                self.email_list.blockSignals(False)
                restored = True

        if restored:
            # 正在阅读的邮件仍在列表中：保留阅读窗格内容 + 按钮可用
            self._selected_email = MailCacheRepository.get_by_id(prev_selected_id)
            self.reply_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
        else:
            # 之前选中的邮件已不在（换文件夹/已删除）→ 清空阅读区
            self.reading_pane.clear()
            if self._attachment_bar is not None:
                self._attachment_bar.setParent(None)
                self._attachment_bar = None

    def _on_email_clicked(self, item: QListWidgetItem):
        """点击邮件：读取正文 → HTML 渲染 + 显示附件栏 + 标记已读。"""
        email_id = item.data(Qt.UserRole)
        email = MailCacheRepository.get_by_id(email_id)
        if not email:
            return

        # 记录选中邮件（回复/删除按钮的目标）并启用按钮
        self._selected_email = email
        self.reply_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

        # ── 阅读窗格渲染：HTML 信头卡片 + 正文 ──
        # 所有用户内容经 html.escape 转义，安全无 XSS。
        # 此前用 setPlainText 拼接信头，\n 与正文混在一起，视觉层级不清；
        # 改为 HTML 后信头成为独立卡片，正文区清晰分隔。
        self._render_reading_pane(email)

        # 显示附件栏（非内联附件）
        self._show_attachments(email_id)

        # 标记已读
        if not email.get("is_read", 0):
            MailCacheRepository.mark_read(email_id)
            # 更新列表项样式（去掉高亮条 + 加粗）
            widget = self.email_list.itemWidget(item)
            if isinstance(widget, _EmailListItem):
                widget._is_read = True
                # 重新创建列表项以刷新样式（简单可靠）
                self._refresh_item_widget(item, email_id)

    def _render_reading_pane(self, email: dict):
        """渲染阅读窗格：信头（头像 + 发件人 + 主题 + 时间）+ 分隔线 + 正文。

        参考 Outlook/Gmail 布局：左侧头像、中部发件人/时间、右侧日期；
        信头与正文之间用分隔线隔开，视觉层级清晰。
        正文优先渲染 HTML 原文（表格/富文本样式不丢，V1.5），
        无 HTML 时回落纯文本。
        """
        t = theme_current()

        sender = html.escape(email.get("sender", "") or "")
        sender_addr = html.escape(email.get("sender_addr", "") or "")
        # 联系人命名优先：信头无显示名时用联系人页里起的名字
        cname = MailContactRepository.get_name_map().get(
            (email.get("sender_addr") or "").strip())
        if cname:
            sender = html.escape(cname)
        subject = html.escape(email.get("subject", "") or "(无主题)")
        received = html.escape(email.get("received_at", "") or "")
        # 正文：有 HTML 原文 → 净化后渲染（表格按表格显示）；
        # 否则纯文本转义 + 换行转 <br>
        body_html_raw = (email.get("body_html", "") or "").strip()
        if body_html_raw:
            viewport_w = self.reading_pane.viewport().width()
            max_width = max(0, viewport_w - 16)
            # 居中卡片容器（模拟网页版邮件的居中阅读列）：
            # 最大 700px、窄窗格时全宽；邮件内部表格宽度统一收敛到卡片宽
            card_w = min(700, max_width) if max_width > 0 else 700
            # 先渲染（图片后台异步下载，不阻塞 UI）
            body = _sanitize_email_html(
                body_html_raw, max_width=max_width, fill_px=card_w,
                download_images=False)
            body = (f'<table align="center" width="{card_w}">'
                    f'<tr><td>{body}</td></tr></table>')
            self._last_render_width = viewport_w
        else:
            body = html.escape(
                email.get("body_text", "") or "").replace("\n", "<br>")
            self._last_render_width = 0
        # 头像首字
        avatar_initial = (sender or "?")[0]

        html_content = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:{t.SURFACE};">
<!-- 外层留白：内容区与浏览器边框之间的呼吸空间 -->
<div style="padding:36px 40px;">
  <!-- 内层卡片：信头 + 正文（与外层同色，靠边框+圆角区分层次） -->
  <div style="background:{t.SURFACE};border:1px solid {t.BORDER};
       border-radius:12px;overflow:hidden;">
    <!-- 信头区域 -->
    <div style="padding:20px 24px 0 24px;">
      <!-- 主题 -->
      <div style="font-size:18px;font-weight:bold;color:{t.FG};
           margin-bottom:16px;line-height:1.4;">{subject}</div>
      <!-- 发件人行：头像 + 信息 -->
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
        <tr>
          <!-- 头像圆圈 -->
          <td style="width:44px;vertical-align:top;padding-top:2px;">
            <div style="width:40px;height:40px;border-radius:50%;
                 background-color:{t.SOFT};color:{t.FG};
                 font-size:16px;font-weight:bold;
                 text-align:center;line-height:40px;">{avatar_initial}</div>
          </td>
          <!-- 发件人 + 地址 -->
          <td style="vertical-align:top;padding-left:10px;">
            <div style="font-size:14px;font-weight:600;color:{t.FG};">{sender}</div>
            <div style="font-size:12px;color:{t.MUTED};margin-top:2px;">&lt;{sender_addr}&gt;</div>
          </td>
          <!-- 时间（右对齐） -->
          <td style="vertical-align:top;text-align:right;white-space:nowrap;">
            <div style="font-size:12px;color:{t.MUTED};">{received}</div>
          </td>
        </tr>
      </table>
    </div>
    <!-- 分隔线：信头与正文的明确分界。
         空单元格在 QTextBrowser 会塌缩为零高度（height 属性无效），
         必须用 &nbsp; 字符撑起行高，bgcolor 填满整行宽度。 -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="margin:12px 0;border-collapse:collapse;">
      <tr bgcolor="{t.MUTED}">
        <td style="font-size:4px;line-height:4px;">&nbsp;</td>
      </tr>
    </table>
    <!-- 正文区域 -->
    <div style="color:{t.FG};font-size:14px;line-height:1.8;
         padding:8px 28px 24px 28px;">
      {body}
    </div>
  </div>
</div>
</body></html>"""
        self.reading_pane.setHtml(html_content)
        # 异步下载远程图片（不阻塞 UI，下载完后经信号回主线程更新）
        if body_html_raw:
            self._load_images_async(
                email.get("id", 0), body_html_raw, html_content)

    def _load_images_async(self, email_id: int, body_html_raw: str,
                           current_html: str):
        """后台线程下载邮件中的远程图片，完成后发 images_ready 信号。

        信号从后台线程 emit 是线程安全的（Qt 自动转队列连接，槽在
        主线程执行）。不能用 QTimer.singleShot——它要求调用线程有
        事件循环，后台线程没有，定时器创建后永不触发。
        """
        import re
        import threading
        # 收集所有远程图片 URL
        urls = re.findall(
            r'src\s*=\s*["\'](https?://[^"\']+)["\']',
            body_html_raw, flags=re.IGNORECASE)
        if not urls:
            return
        # 去重
        urls = list(dict.fromkeys(urls))

        def _download_and_update():
            replacements = {}
            for url in urls:
                b64 = _download_image_b64(url)
                if b64:
                    replacements[url] = b64
            if replacements:
                new_html = current_html
                for orig, b64 in replacements.items():
                    # 整体重写 img 标签（按真实纵横比写显式宽高，
                    # 修掉邮件里 height="auto" 造成的文字重叠）
                    new_html = _rewrite_img_tag(new_html, orig, b64)
                # 跨线程投递到主线程（queued connection）
                self.images_ready.emit(new_html, email_id)

        threading.Thread(target=_download_and_update, daemon=True).start()

    def _on_images_ready(self, new_html: str, email_id: int):
        """图片下载完成（主线程）：更新阅读窗格。

        过期守卫：下载期间用户可能已切换到别的邮件，
        只更新仍在阅读的那封，避免覆盖新选择的内容。
        """
        cur = self._selected_email or {}
        if cur.get("id") == email_id:
            self.reading_pane.setHtml(new_html)

        import threading
        threading.Thread(target=_download_and_update, daemon=True).start()

    def _show_attachments(self, email_id: int):
        """显示邮件附件栏（仅非内联附件）。

        附件栏位于阅读窗格下方，每个附件一个按钮，点击保存到用户指定位置。
        """
        # 清除旧附件栏
        if self._attachment_bar is not None:
            self._attachment_bar.setParent(None)
            self._attachment_bar = None

        attachments = MailCacheRepository.get_attachments(email_id)
        non_inline = [a for a in attachments if not a["is_inline"]]
        if not non_inline:
            return

        bar = QFrame()
        bar.setObjectName("mailAttachmentBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        for att in non_inline:
            size_str = self._format_size(att["size"])
            btn = QPushButton(f"📄 {att['filename']} ({size_str})")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, a=att: self._save_attachment(a))
            layout.addWidget(btn)

        layout.addStretch()

        # 将附件栏插入到右侧面板底部（阅读窗格下方）
        right_panel = self.reading_pane.parentWidget()
        right_panel.layout().addWidget(bar)
        self._attachment_bar = bar
        # 刷新主题样式
        self._apply_styles()

    def _save_attachment(self, att):
        """保存附件到用户选择的位置。"""
        from PySide6.QtWidgets import QFileDialog
        dest, _ = QFileDialog.getSaveFileName(self, tr("保存附件"), att["filename"])
        if dest:
            import shutil
            shutil.copy2(att["saved_path"], dest)

    @staticmethod
    def _format_size(size) -> str:
        """格式化文件大小为人类可读字符串。"""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / 1024 / 1024:.1f}MB"

    def _refresh_item_widget(self, item: QListWidgetItem, email_id: int):
        """重新创建列表项 widget 以刷新已读样式。"""
        email = MailCacheRepository.get_by_id(email_id)
        if not email:
            return
        email = self._apply_contact_names(email, MailContactRepository.get_name_map())
        email["is_read"] = 1  # 强制已读
        widget = _EmailListItem(email)
        widget.apply_style()
        self.email_list.setItemWidget(item, widget)

    def _on_selection_changed(self):
        """选择变化时：更新按钮状态 + 计数标签 + 当前阅读邮件。"""
        selected_items = self.email_list.selectedItems()
        count = len(selected_items)

        # 更新按钮状态：有选中时删除/回复可用
        self.delete_btn.setEnabled(count > 0)
        self.reply_btn.setEnabled(count > 0)

        # 更新计数标签
        if count > 1:
            self._selection_label.setText(f"{tr('已选')}{count}{tr(' 封')}")
        else:
            self._selection_label.setText("")

        # 当前阅读邮件：取第一个选中的（用于右侧阅读窗格 + 回复目标）
        if selected_items:
            first_item = selected_items[0]
            email_id = first_item.data(Qt.UserRole)
            self._selected_email = MailCacheRepository.get_by_id(email_id)
        else:
            self._selected_email = None

    def _on_refresh(self):
        """点击刷新按钮：发射信号通知 MainWindow 执行后台拉取。"""
        self.refresh_requested.emit()

    def _on_reply(self):
        """点击回复按钮：发射信号（无选中时按钮本就禁用，双保险）。"""
        if self._selected_email:
            self.reply_requested.emit()

    def _on_delete(self):
        """点击删除按钮：发射信号（无选中时按钮本就禁用，双保险）。"""
        if self.selected_emails:
            self.delete_requested.emit()
