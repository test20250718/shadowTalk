# shadowtalk/ui/main_window.py
"""
ShadowTalk 主窗口
设计参考：shadowtalk-chat.html — 左侧 328px 侧边栏 + 右侧聊天面板
"""
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QMessageBox, QDialog,
    QMenuBar, QMenu, QStatusBar, QLabel, QHBoxLayout, QWidget,
    QStackedWidget, QToolBar,
)
from PySide6.QtCore import QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from datetime import datetime
import logging

from shadowtalk.ui.widgets.friend_list import FriendListWidget
from shadowtalk.ui.widgets.chat_area import ChatArea
from shadowtalk.ui.widgets.friend_dialog import FriendDialog
from shadowtalk.ui.threads.ai_worker import AIWorker
from shadowtalk.core.memory_engine import build_context
from shadowtalk.core.ai_client import AIClient
from shadowtalk.core.friend_service import FriendService, resolve_avatar
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.core.prompt_logger import log_conversation
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository,
    MailCacheRepository,
)
from shadowtalk.config.settings import Settings
from shadowtalk.config.paths import resource_path
from shadowtalk.config.i18n import tr, on_language_changed
from shadowtalk.ui import theme


logger = logging.getLogger(__name__)


def _now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class MainWindow(QMainWindow):
    approval_answered = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ShadowTalk 影聊")
        self.resize(1100, 720)
        self.setMinimumSize(860, 560)
        self.current_friend_id = None
        self.ai_worker = None
        self._retired_workers = []   # 已 terminate 的在途旧 worker 保留列表（防 QThread 运行中销毁）
        self._retired_mail_fetch_workers = []  # 在途邮件拉取 worker 保留列表（防窗口关闭时崩溃）
        self.ai_client = None
        self._pending_context = None      # 暂存当次对话的上下文（供日志用）
        self._pending_friend_name = ""    # 暂存当次对话的好友名（供日志用）

        # ── 全局样式 ──
        self.setStyleSheet(theme.global_qss())

        # ── 核心组件 ──
        # 新增垂直 Tab 栏 + 邮箱面板；FriendListWidget 与 ChatArea 零修改，
        # 原样放入 QStackedWidget 作为 page 0，聊天功能完全保留。
        from shadowtalk.ui.widgets.vertical_tab_bar import VerticalTabBar
        from shadowtalk.ui.widgets.mail_widget import MailWidget
        from shadowtalk.ui.widgets.contacts_widget import ContactsWidget

        self.tab_bar = VerticalTabBar()
        self.friend_list = FriendListWidget()
        self.chat_area = ChatArea()
        self.mail_widget = MailWidget()
        self.contacts_widget = ContactsWidget()

        # 左面板：仅聊天模式使用（好友列表）；邮箱模式隐藏整列，
        # 邮件列表占满宽度（原文件夹列表只有硬编码项且刷新只拉
        # INBOX，已发送/草稿/垃圾从未真正可用，按用户要求移除）
        self.left_panel = QStackedWidget()
        self.left_panel.addWidget(self.friend_list)      # index 0

        # 邮箱页内部双视图：邮件列表 ↔ 联系人管理（同页切换，不占独立 Tab）
        self.mail_page = QStackedWidget()
        self.mail_page.addWidget(self.mail_widget)       # index 0 邮件
        self.mail_page.addWidget(self.contacts_widget)   # index 1 联系人

        # 右面板堆叠（聊天区 / 邮箱页）
        self.right_panel = QStackedWidget()
        self.right_panel.addWidget(self.chat_area)   # index 0
        self.right_panel.addWidget(self.mail_page)   # index 1

        # 3 栏 splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tab_bar)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([50, 280, 770])
        splitter.setHandleWidth(3)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        # ── 信号连接 ──
        self.friend_list.friend_selected.connect(self._on_friend_selected)
        self.friend_list.add_btn.clicked.connect(self._on_add_friend)
        # 用弱引用注入回调，避免 MainWindow → friend_list → 绑定方法 → MainWindow
        # 引用循环。该循环会让窗口在测试中延迟到 gc 才销毁，导致 ChatArea 装在全局的
        # 事件过滤器（closeEvent 对子控件不触发，无法移除）跨窗口存活，其 filter 体在
        # 下一窗口构建时访问已释放控件 → 堆损坏 → segfault。弱引用打破循环后窗口随即
        # 销毁，Qt 自动摘除其全局过滤器。
        import weakref
        self._self_ref = weakref.ref(self)
        self.friend_list._edit_callback = lambda fid, _s=self._self_ref: (
            _s() and _s()._on_edit_friend(fid))
        self.friend_list._delete_callback = lambda fid, _s=self._self_ref: (
            _s() and _s()._on_delete_friend(fid))
        self.friend_list._room_callback = lambda _s=self._self_ref: (
            _s() and _s()._on_open_room())
        self.friend_list._import_callback = lambda _s=self._self_ref: (
            _s() and _s()._on_import_asset())
        self.chat_area.message_sent.connect(self._on_message_sent)
        self.chat_area.status_message.connect(self._on_status_message)
        # 主题切换已移至工具栏（聊天区不再含主题按钮）

        # Tab 栏切换 → 同步左右面板
        self.tab_bar.tab_changed.connect(self._on_tab_changed)
        # 邮箱写信按钮
        self.mail_widget.compose_btn.clicked.connect(self._on_compose)
        # 邮箱刷新按钮 → 后台拉取邮件（原缺失，导致点刷新无反应）
        self.mail_widget.refresh_requested.connect(self._on_mail_refresh)
        # 邮箱回复 / 删除按钮
        self.mail_widget.reply_requested.connect(self._on_reply_mail)
        self.mail_widget.delete_requested.connect(self._on_delete_mail)
        # 联系人页写信（复用写信对话框与发送链路）
        self.contacts_widget.compose_requested.connect(self._on_compose_to)
        # 邮箱页内视图切换：邮件列表 ↔ 联系人
        self.mail_widget.contacts_requested.connect(self._show_contacts_view)
        self.contacts_widget.back_requested.connect(self._show_mail_view)

        # ── 后台扫描 ──
        self.scanner = BackgroundScanner()
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scanner.scan_now)
        self.scan_timer.start(3600 * 1000)

        # ── 邮件同步（V1.4-Add）──
        self.mail_sync_timer = QTimer()
        self.mail_sync_timer.timeout.connect(self._on_mail_sync_tick)
        self._retired_mail_workers = []   # 退休的邮件发送 worker（防 GC）
        self._mail_send_worker = None     # 当前发送 worker（串行发送，避免并发连接）
        self._sync_queue = []             # 待发送好友队列（自动到期/手动触发共用）
        self._mail_sync_any_sent = False  # 本轮是否有实际发送（用于状态提示）

        # ── 菜单栏 ──
        self._build_menu()

        # ── 工具栏（模型切换 + 主题切换 + 语言切换）──
        from shadowtalk.ui.widgets.toolbar import Toolbar
        self.toolbar = Toolbar(self)
        self.addToolBar(self.toolbar)
        self.toolbar.model_changed.connect(self._on_model_changed)
        # 语言切换后刷新菜单 + 状态栏
        on_language_changed(self._retranslate_ui)

        # ── 状态栏 ──
        self._build_statusbar()

        # ── Toast 提示（邮件发送结果等需要明确反馈的场景）──
        from shadowtalk.ui.widgets.toast import Toast
        self.toast = Toast(self)

        # ── 加载数据 ──
        self._load_friends()
        # 未选中好友时聊天区显示空白（微信风格）
        self.chat_area.show_empty_state()

        # ── 邮件同步启动（定时 + 立即触发一次）──
        self._start_mail_sync_timer()
        # 延迟启动一次同步（等 UI 就绪后），仅当配置非空
        QTimer.singleShot(1000, self._on_mail_sync_tick)

        # ── 邮件接收（IMAP 轮询 + 启动拉取）──
        self.mail_receive_timer = QTimer()
        self.mail_receive_timer.timeout.connect(self._on_mail_receive_tick)
        self._mail_receive_worker = None
        self._start_mail_receive_timer()
        # 延迟启动一次接收（等 UI 就绪后）
        QTimer.singleShot(1500, self._on_mail_receive_tick)

        # ── 邮箱客户端自动刷新（定时拉取当前文件夹）──
        # 此前邮箱只在切 Tab 和点刷新按钮时拉取，用户一直开着邮箱却收不到新邮件。
        # 新增定时器按 mail_poll_interval_seconds 间隔自动刷新当前文件夹。
        self.mail_auto_refresh_timer = QTimer()
        self.mail_auto_refresh_timer.timeout.connect(self._on_mail_auto_refresh_tick)
        self._start_mail_auto_refresh_timer()

    def _build_menu(self):
        menu_bar = self.menuBar()
        menu_bar.clear()
        settings_menu = menu_bar.addMenu(tr("设置"))
        settings_action = settings_menu.addAction(tr("API 与记忆参数"))
        settings_action.triggered.connect(self._on_open_settings)

        help_menu = menu_bar.addMenu(tr("帮助"))
        help_doc_action = help_menu.addAction(tr("帮助文档"))
        help_doc_action.triggered.connect(self._on_open_help_doc)
        about_action = help_menu.addAction(tr("关于 影聊"))
        about_action.triggered.connect(self._on_open_about)

    def _on_open_about(self):
        from shadowtalk.ui.widgets.about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _on_open_help_doc(self):
        """打开用户手册 PDF（系统默认 PDF 阅读器）。

        根据当前语言选择中文版 / 英文版手册。
        """
        from shadowtalk.config.i18n import language
        lang = language()
        pdf_name = ("shadowtalk_manual_en.pdf"
                    if lang == "en" else "shadowtalk_manual.pdf")
        pdf_path = resource_path(f"resources/{pdf_name}")
        if not pdf_path.exists():
            # 英文版缺失时回退中文版
            fallback = resource_path("resources/shadowtalk_manual.pdf")
            if fallback.exists():
                pdf_path = fallback
            else:
                QMessageBox.warning(
                    self, tr("提示"),
                    tr("用户手册文件缺失，请重新安装应用。"))
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path)))

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        import shadowtalk
        self._version = shadowtalk.__version__
        self._status_label = QLabel(tr("就绪 · 影聊 v") + self._version)
        self.status_bar.addWidget(self._status_label)
        # AI 输出声明：常驻右侧（permanent 区），不与瞬时提示
        # （语音合成失败等，showMessage 6 秒消失）互相挤占。
        # 颜色由全局 QSS 的 QStatusBar QLabel 规则按主题自动适配。
        self._disclaimer_label = QLabel(tr("AI 输出仅供参考，请审慎甄别，切勿直接采信"))
        self.status_bar.addPermanentWidget(self._disclaimer_label)

    def _on_open_settings(self):
        from shadowtalk.ui.widgets.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, self.current_friend_id)
        # 保存后刷新工具栏模型列表（API 配置可能增删/切换）
        dialog.settings_saved.connect(self.toolbar.refresh)
        dialog.exec()
        # 无论是否点保存，都刷新工具栏（保险起见）
        self.toolbar.refresh()
        # 设置可能改了轮询间隔，用新间隔重启三个邮件定时器（无需重启软件）
        self._start_mail_sync_timer()
        self._start_mail_receive_timer()
        self._start_mail_auto_refresh_timer()

    def _load_friends(self):
        # 先填充每个好友的最后一条消息（会话预览），再渲染列表
        for fid, (content, create_time) in MessageRepository.get_last_per_friend().items():
            self.friend_list.set_last_message(
                fid, content[:30], create_time[11:16]  # 'HH:MM'
            )
        friends = [dict(f) for f in FriendRepository.get_all()]
        for f in friends:
            f["avatar_path"] = resolve_avatar(f["avatar_path"])
        self.friend_list.load_friends(friends)

    def _on_theme_changed(self, name: str):
        theme.set_current(name)
        self._apply_theme()
        # 主题切换后同步工具栏主题按钮图标
        self.toolbar._sync_theme_button()

    def _on_model_changed(self, index: int):
        """工具栏切换模型：重置缓存的 AIClient（下次发消息用新配置）。"""
        # flat keys 已由 Toolbar 写入，这里只需清缓存让下次聊天重建 AIClient
        self.ai_client = None

    def _retranslate_ui(self):
        """语言切换后刷新菜单栏 + 状态栏文本。"""
        self._build_menu()
        self._status_label.setText(tr("就绪 · 影聊 v") + self._version)
        self._disclaimer_label.setText(tr("AI 输出仅供参考，请审慎甄别，切勿直接采信"))

    def _apply_theme(self):
        """即时切换主题：重设全局 QSS + 容器样式 + 重建好友列表与消息列表（spec 3.4）"""
        self.setStyleSheet(theme.global_qss())
        self.toolbar.restyle()
        self.friend_list.restyle()
        self.chat_area.restyle()
        # 新增邮箱组件的 restyle（主题切换时同步刷新）
        self.tab_bar.restyle()
        self.mail_widget.restyle()
        self.contacts_widget.restyle()
        self._load_friends()
        if self.current_friend_id:
            self.chat_area.clear_messages()
            self._load_history_messages(self.current_friend_id)

    def _on_friend_selected(self, friend_id: int):
        self.current_friend_id = friend_id
        self.chat_area.show_conversation()
        self.chat_area.clear_messages()
        friend = FriendRepository.get_by_id(friend_id)
        if friend:
            name = friend["remark"] or friend["name"]
            self.chat_area.set_friend_info(
                friend_id, name, resolve_avatar(friend["avatar_path"]),
                friend["voice"])
            # 冻结态：已授权作废的分身禁用输入
            self.chat_area.set_frozen(bool(friend["asset_revoked"]))
        self._load_history_messages(friend_id)

    def _load_history_messages(self, friend_id: int):
        # 界面只渲染最近 50 条（用户定夺：聊天只关注当下，更久的
        # 对话已转入 AI 的记忆摘要，不翻历史；加载也永远轻快）。
        # 记忆引擎仍读全量，她的记忆不受影响。
        msgs = MessageRepository.get_unarchived(friend_id, limit=50)
        if msgs:
            self.chat_area.add_day_divider("今天")
        for m in msgs:
            # DB 存 human_reply，气泡组件的角色名是 human（不映射的话
            # 重启后真人回信会掉进 else 分支，渲染成 AI 样式气泡）
            role = ("human" if m["sender_type"] == "human_reply"
                    else m["sender_type"])
            self.chat_area.add_message(m["content"], role, m["create_time"], m["id"])

    def _on_add_friend(self):
        dialog = FriendDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            FriendService.create(
                name=data["name"],
                remark=data["remark"],
                system_prompt=data["system_prompt"],
                avatar_source_path=data["avatar_path"],
                ai_role=data.get("ai_role", ""),
                user_role=data.get("user_role", ""),
                work_dir=data.get("work_dir", ""),
                voice=data.get("voice", ""),
            )
            self._load_friends()

    def _on_import_asset(self):
        """导入网页数字分身资产：粘贴密文 -> 解密 -> 预览 -> 落库。"""
        from shadowtalk.ui.widgets.asset_import_dialog import AssetImportDialog
        from shadowtalk.ui.widgets.asset_preview_dialog import AssetPreviewDialog
        from shadowtalk.core.asset_import_service import (
            AssetImportService, InvalidCipherError, RevokedAssetError,
        )

        # 第一步：粘贴密文
        import_dialog = AssetImportDialog(self)
        if import_dialog.exec() != QDialog.Accepted:
            return
        ciphertext = import_dialog.get_ciphertext()

        # 第二步：解密 + 解析（仅预览，不落库）
        try:
            bundle = AssetImportService.decrypt_and_parse(ciphertext)
        except InvalidCipherError as e:
            QMessageBox.critical(self, tr("提示"), str(e))
            return

        # 第三步：预览确认（判断是否重导入）
        existing = FriendRepository.find_by_authorizer_recipient(
            bundle.authorizer_email, bundle.recipient_email
        )
        is_update = (existing is not None and not existing["asset_revoked"])
        preview_dialog = AssetPreviewDialog(bundle, is_update=is_update, parent=self)
        if preview_dialog.exec() != QDialog.Accepted:
            return

        # 第四步：落库
        try:
            friend_id = AssetImportService.import_asset(ciphertext)
        except (RevokedAssetError, InvalidCipherError) as e:
            QMessageBox.critical(self, tr("提示"), str(e))
            return

        self._load_friends()
        self.status_bar.showMessage(f"{tr('成功导入分身：')}{bundle.nickname}", 6000)

    def _on_edit_friend(self, friend_id: int):
        friend = FriendRepository.get_by_id(friend_id)
        if not friend:
            return
        dialog = FriendDialog(self, friend)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            # 头像单独处理：复制到应用头像目录并清理旧文件
            if data["avatar_path"] and data["avatar_path"] != friend["avatar_path"]:
                FriendService.update_avatar(friend_id, data["avatar_path"])
            FriendRepository.update(
                friend_id,
                name=data["name"],
                remark=data["remark"],
                system_prompt=data["system_prompt"],
                ai_role=data.get("ai_role", ""),
                user_role=data.get("user_role", ""),
                work_dir=data.get("work_dir", ""),
                voice=data.get("voice", ""),
                # 邮件同步字段（仅手动创建的好友会包含这些键）
                mail_sync_enable=data.get("mail_sync_enable", 0),
                mail_receiver_address=data.get("mail_receiver_address", ""),
                mail_sync_cycle=data.get("mail_sync_cycle", "daily"),
            )
            self._load_friends()
            # 若正在编辑当前聊天的好友，刷新聊天头部（名称/头像）
            if self.current_friend_id == friend_id:
                updated = FriendRepository.get_by_id(friend_id)
                if updated:
                    name = updated["remark"] or updated["name"]
                    self.chat_area.set_friend_info(
                        friend_id, name, resolve_avatar(updated["avatar_path"]),
                        updated["voice"]
                    )

    def _on_delete_friend(self, friend_id: int):
        FriendService.delete(friend_id, keep_messages=False)
        self.current_friend_id = None
        self.chat_area.clear_messages()
        self.chat_area.show_empty_state()
        self._load_friends()

    def _on_open_room(self):
        """沉浸式聊天入口：选好友 → 直接进入咖啡馆"""
        friends = FriendRepository.get_all()
        if not friends:
            self.status_bar.showMessage(tr("还没有好友，先添加一位再沉浸式聊天"), 6000)
            return
        # 重名好友显示名追加 id 区分，避免按名匹配选错人
        from collections import Counter
        from PySide6.QtWidgets import QInputDialog
        displays = [f["remark"] or f["name"] for f in friends]
        dup = {n for n, c in Counter(displays).items() if c > 1}
        items = []
        display_to_id = {}
        for f, disp in zip(friends, displays):
            item = f"{disp}（{f['id']}）" if disp in dup else disp
            items.append(item)
            display_to_id[item] = f["id"]
        name, ok = QInputDialog.getItem(
            self, tr("沉浸式聊天"), tr("和谁在咖啡馆聊？"), items, 0, False)
        if not ok:
            return
        friend_id = display_to_id[name]
        from shadowtalk.ui.widgets.room_window import RoomWindow
        room = RoomWindow(friend_id, "cafe", parent=self)
        # 离开沉浸式聊天 → 刷新主界面：当前好友的聊天区重载 + 会话列表预览更新
        room.finished.connect(lambda: self._on_room_closed(friend_id))
        room.show_in_screen()  # 铺满可用区域（排除任务栏，输入条不被挡）

    def _on_room_closed(self, friend_id: int):
        """咖啡馆里聊的消息直接落库，主界面需主动重载显示"""
        if self.current_friend_id != friend_id:
            return
        self.chat_area.clear_messages()
        self._load_history_messages(friend_id)
        last = MessageRepository.get_last_per_friend().get(friend_id)
        if last:
            self.friend_list.set_last_message(
                friend_id, last[0][:30], last[1][11:16])

    # ── V1.4-Add 邮件同步 ──

    def _start_mail_sync_timer(self):
        """启动邮件同步定时器（间隔从设置读取，DevMode 30s）。"""
        if Settings.get_bool("mail_dev_mode"):
            interval = 30 * 1000  # MailHog 测试：30 秒
        else:
            interval = Settings.get_int("mail_poll_interval_seconds") * 1000
        self.mail_sync_timer.start(interval)

    def _on_mail_sync_tick(self):
        """邮件同步定时触发：检查到期好友并入队发送。"""
        # 开发模式用 MailHog 预设；正式环境未配置 SMTP 则跳过
        if not Settings.get_bool("mail_dev_mode") and not Settings.get("mail_smtp_host"):
            return

        from shadowtalk.core.mail_sync_scheduler import MailSyncScheduler
        due_ids = MailSyncScheduler.sync_due_friends()
        if due_ids:
            self._sync_queue = due_ids
            self._mail_sync_any_sent = False
            self.status_bar.showMessage(tr("正在同步邮件…"))
            self._dispatch_next_send()

    def _dispatch_next_send(self):
        """串行派发队列中的下一个好友（worker 空闲时；无新消息的好友跳过）。"""
        if self._mail_send_worker and self._mail_send_worker.isRunning():
            return
        while self._sync_queue:
            fid = self._sync_queue.pop(0)
            if self._send_mail_for_friend(fid):
                self._mail_sync_any_sent = True
                break  # worker 已启动，完成回调后继续派发
        else:
            # 队列已空且本轮未启动任何 worker（全部无新消息）
            if not self._mail_sync_any_sent:
                self.status_bar.showMessage(tr("邮件同步完成（无新消息）"), 4000)

    def _send_mail_for_friend(self, friend_id: int) -> bool:
        """为单个好友组装并发送邮件。返回是否启动了 worker。"""
        from shadowtalk.core.mail_sync_scheduler import MailSyncScheduler
        from shadowtalk.ui.threads.mail_send_worker import MailSendWorker

        info = MailSyncScheduler.due_info(friend_id)
        messages = info["messages"]
        if not messages:
            return False
        session_id = info["session_id"]

        # 构造 mail_config
        if Settings.get_bool("mail_dev_mode"):
            mail_config = {
                "host": "127.0.0.1", "port": 1025,
                "use_tls": False, "username": "", "password": "",
            }
        else:
            mail_config = {
                "host": Settings.get("mail_smtp_host"),
                "port": Settings.get_int("mail_smtp_port"),
                "use_tls": Settings.get_bool("mail_smtp_use_tls"),
                "username": Settings.get("mail_smtp_user"),
                "password": Settings.get("mail_smtp_password"),
            }

        worker = MailSendWorker(friend_id, messages, mail_config, session_id)
        worker.sent.connect(self._on_mail_sent)
        worker.failed.connect(self._on_mail_failed)
        self._mail_send_worker = worker
        worker.start()
        return True

    def _on_mail_sent(self, friend_id: int, message_id: str):
        """邮件发送成功：更新游标，继续派发队列。"""
        from shadowtalk.core.mail_sync_scheduler import MailSyncScheduler
        from shadowtalk.data.repositories import FriendRepository
        friend = FriendRepository.get_by_id(friend_id)
        if friend:
            # 更新游标到已发消息的最大 id
            messages = MessageRepository.get_messages_since(
                friend_id, friend["last_sent_message_id"]
            )
            if messages:
                last_msg_id = max(m["id"] for m in messages)
                MailSyncScheduler.mark_sent(friend_id, last_msg_id)
        # 队列已空则清除进度提示，否则继续派发
        if not self._sync_queue:
            self.status_bar.showMessage(tr("邮件同步完成"), 4000)
        else:
            self.status_bar.showMessage(f"{tr('正在同步邮件…（剩余')} {len(self._sync_queue)}{tr(' 位）')}")
        self._dispatch_next_send()

    def _on_mail_failed(self, friend_id: int, reason: str):
        """邮件发送失败：记录日志，继续派发队列。"""
        logger.error("邮件发送失败 friend_id=%s：%s", friend_id, reason)
        # 队列已空则显示最终结果，否则继续派发
        if not self._sync_queue:
            self.status_bar.showMessage(f"{tr('邮件同步完成（有失败：')}{reason}）", 6000)
        else:
            self.status_bar.showMessage(f"{tr('正在同步邮件…（剩余')} {len(self._sync_queue)}{tr(' 位）')}")
        self._dispatch_next_send()

    # ── V1.4-Add 邮件接收（IMAP）──

    def _start_mail_receive_timer(self):
        """启动邮件接收定时器（间隔从设置读取）。"""
        interval = Settings.get_int("mail_poll_interval_seconds") * 1000
        self.mail_receive_timer.start(interval)

    def _start_mail_auto_refresh_timer(self):
        """启动邮箱客户端自动刷新定时器（复用 mail_poll_interval_seconds 间隔）。

        只在用户停留在邮箱 Tab 时才真正发起拉取，避免在聊天界面后台无谓轮询。
        """
        interval = Settings.get_int("mail_poll_interval_seconds") * 1000
        self.mail_auto_refresh_timer.start(interval)

    def _on_mail_auto_refresh_tick(self):
        """邮箱客户端自动刷新 tick：仅在邮箱 Tab 可见时触发。"""
        # 不在邮箱 Tab 则跳过（right_panel index 1 = 邮箱页）
        if self.right_panel.currentIndex() != 1:
            return
        # 未配置 IMAP 则跳过
        if not Settings.get("mail_imap_host"):
            return
        # 上一个拉取 worker 还在跑则跳过（避免并发覆盖）
        if getattr(self, '_mail_fetch_worker', None) and self._mail_fetch_worker.isRunning():
            return
        # 静默刷新：不弹 Toast，不打扰用户（区别于手动刷新）
        self._on_mail_refresh(silent=True)

    def _on_mail_receive_tick(self):
        """邮件接收定时触发：拉取未读邮件并处理。"""
        # 未配置 IMAP 则跳过
        if not Settings.get("mail_imap_host"):
            return
        # 上一个 worker 仍在跑则等待
        if self._mail_receive_worker and self._mail_receive_worker.isRunning():
            return

        imap_config = self._get_imap_config()
        if not imap_config:
            return

        # AI 客户端（用于授权意图兜底判断，可选）
        ai_client = None
        try:
            ai_client = self._get_ai_client()
        except Exception:
            pass  # AI 不可用时跳过 AI 兜底

        # 局部 import（镜像 _send_mail_for_friend 的 MailSendWorker 模式）。
        # 曾经漏了这句：定时器每 5 分钟触发一次 NameError，邮件接收
        # 从未跑通，回信永远收不到（用户报告：发送正常但收不到回复）
        from shadowtalk.ui.threads.mail_receive_worker import MailReceiveWorker
        worker = MailReceiveWorker(imap_config, ai_client=ai_client)
        worker.human_reply.connect(self._on_human_reply)
        worker.asset_revoked.connect(self._on_asset_revoked)
        worker.finished.connect(lambda: self.status_bar.showMessage(tr("邮件接收完成"), 4000))
        worker.failed.connect(lambda reason: self.status_bar.showMessage(
            f"{tr('邮件接收失败：')}{reason}", 6000
        ))
        self._mail_receive_worker = worker
        self.status_bar.showMessage(tr("正在接收邮件…"))
        worker.start()

    def _get_imap_config(self) -> dict | None:
        """构造 IMAP 配置字典。"""
        if Settings.get_bool("mail_dev_mode"):
            return {
                "host": "127.0.0.1", "port": 1143, "user": "", "password": "",
                "use_ssl": False,
            }
        host = Settings.get("mail_imap_host")
        if not host:
            return None
        return {
            "host": host,
            "port": Settings.get_int("mail_imap_port"),
            "user": Settings.get("mail_imap_user"),
            "password": Settings.get("mail_imap_password"),
            "use_ssl": True,
        }

    def _on_human_reply(self, friend_id: int, text: str, message_id: str):
        """收到真人回信：插入聊天窗口。"""
        from shadowtalk.data.repositories import MessageRepository
        ts = _now_timestamp()
        # 插入 DB（捕获 lastrowid 作为气泡 msg_id，避免与用户消息同占 0）
        round_index = self._next_round_index(friend_id)
        msg_id = MessageRepository.insert(friend_id, "human_reply", text, round_index)
        # 如果当前正在查看该好友，刷新聊天区
        if self.current_friend_id == friend_id:
            self.chat_area.add_message(text, "human", ts, msg_id)
        # 更新会话列表预览
        self.friend_list.set_last_message(friend_id, f"[真人] {text[:25]}", ts[-5:])
        self.status_bar.showMessage(tr("收到真人回信"), 4000)

    def _on_asset_revoked(self, friend_id: int):
        """授权作废：标记 DB + 冻结聊天。"""
        FriendRepository.update(friend_id, asset_revoked=1)
        # 如果当前正在查看该好友，冻结聊天区
        if self.current_friend_id == friend_id:
            self.chat_area.set_frozen(True)
        self.status_bar.showMessage(tr("该分身已被创作者取消授权"), 6000)

    # ── 邮箱客户端（V1.5 新增）──

    def _on_tab_changed(self, index: int):
        """Tab 切换：聊天显示左栏好友列表；邮箱页隐藏左栏全宽显示。"""
        self.right_panel.setCurrentIndex(index)
        if index == 1:
            # 邮箱模式：隐藏左栏，进入时默认显示邮件列表视图
            self.left_panel.hide()
            self.mail_page.setCurrentIndex(0)
            # 先读缓存立即渲染，再触发后台刷新
            self.mail_widget.load_folder("INBOX")
            self._on_mail_refresh()
        else:
            self.left_panel.show()
            self.left_panel.setCurrentIndex(0)

    def _show_contacts_view(self):
        """邮箱页内切到联系人管理视图。"""
        self.mail_page.setCurrentIndex(1)
        self.contacts_widget.reload()

    def _show_mail_view(self):
        """邮箱页内切回邮件列表视图。"""
        self.mail_page.setCurrentIndex(0)

    def _on_mail_refresh(self, folder: str = None, silent: bool = False):
        """刷新邮件：后台 IMAP 拉取 → 写缓存 → 重新渲染。

        folder 默认取当前邮件列表所在文件夹，避免硬编码 INBOX 导致切换文件夹后
        刷新仍然只拉 INBOX、新文件夹永远为空。
        silent=True 为自动定时刷新：不弹 Toast、不打扰用户，仅静默更新列表。
        """
        if not Settings.get("mail_imap_host"):
            if not silent:
                self.toast.show_error(tr("请先在设置中配置 IMAP 邮箱"))
            return
        # 上一个 worker 在跑则跳过
        if getattr(self, '_mail_fetch_worker', None) and self._mail_fetch_worker.isRunning():
            return
        target_folder = folder or self.mail_widget.current_folder
        imap_config = self._get_imap_config()
        if not imap_config:
            return
        from shadowtalk.ui.threads.mail_fetch_worker import MailFetchWorker
        worker = MailFetchWorker(imap_config, target_folder)
        # 用闭包把 target_folder 传给完成回调，确保写缓存+渲染对应同一文件夹
        worker.emails_fetched.connect(
            lambda emails, f=target_folder: self._on_mails_fetched(emails, f, silent=silent))
        if not silent:
            worker.failed.connect(lambda r: self.toast.show_error(f"{tr('收信失败：')}{r}"))
        self._mail_fetch_worker = worker
        self._retired_mail_fetch_workers.append(worker)  # 防 GC 销毁运行中线程
        if not silent:
            self.status_bar.showMessage(tr("正在收信…"))
        worker.start()

    def _on_mails_fetched(self, emails: list, folder: str, silent: bool = False):
        """邮件拉取完成：写缓存 + 提取联系人 + 重新渲染。

        silent=True 为自动定时刷新：仅在有新邮件时静默更新列表，不打扰用户。
        """
        if emails:
            MailCacheRepository.upsert_batch(folder, emails)
            # 顺带更新常用联系人（发件人地址+名称，按频率累计）
            from shadowtalk.data.repositories import MailContactRepository
            MailContactRepository.upsert_contacts(emails)
        self.mail_widget.load_folder(folder)
        if not silent:
            self.toast.show_success(f"{tr('收信完成（')}{len(emails)}{tr(' 封）')}")

    def _on_compose(self):
        """打开写信对话框。"""
        from shadowtalk.ui.widgets.mail_compose_dialog import MailComposeDialog
        dialog = MailComposeDialog(self)
        dialog.send_requested.connect(self._on_send_mail)
        dialog.exec()

    def _on_compose_to(self, address: str):
        """打开写信对话框并预填收件人（联系人页发起）。"""
        from shadowtalk.ui.widgets.mail_compose_dialog import MailComposeDialog
        dialog = MailComposeDialog(self)
        dialog.send_requested.connect(self._on_send_mail)
        dialog.set_recipient(address)
        dialog.exec()

    def _on_reply_mail(self):
        """回复当前选中邮件：预填收件人/主题/引用正文。"""
        email = self.mail_widget.selected_email
        if not email:
            return
        from shadowtalk.ui.widgets.mail_compose_dialog import MailComposeDialog
        dialog = MailComposeDialog(self)
        dialog.send_requested.connect(self._on_send_mail)
        dialog.set_reply_to(email)
        dialog.exec()

    def _on_delete_mail(self):
        """删除选中邮件（支持多选）：确认 → 服务器删除 → 清本地缓存 → 刷新列表。

        服务器删除成功才动本地缓存；失败保留数据可重试。
        """
        emails = self.mail_widget.selected_emails
        if not emails:
            return
        count = len(emails)
        # 确认提示：单封显示主题，多封显示数量
        if count == 1:
            subject = (emails[0].get("subject", "") or tr("（无主题）"))[:40]
            delete_title = tr("确定删除这封邮件吗？\n\n主题：")
            msg = f"{delete_title}{subject}\n\n" + tr("将在服务器收件箱中永久删除（不可恢复）。")
        else:
            delete_msg = tr(" 封邮件吗？\n\n将在服务器收件箱中永久删除（不可恢复）。")
            msg = tr("确定删除选中的") + f"{count}" + delete_msg
        reply = QMessageBox.question(
            self, tr("删除邮件"), msg, QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        imap_config = self._get_imap_config()
        if not imap_config:
            self.toast.show_error(tr("请先在设置中配置 IMAP 邮箱"))
            return
        # 收集所有选中的 email_id 和 message_id
        email_ids = [e.get("id") for e in emails]
        message_ids = [e.get("message_id", "") for e in emails if e.get("message_id")]
        from shadowtalk.ui.threads.mail_delete_worker import MailDeleteWorker
        worker = MailDeleteWorker(imap_config, message_ids)

        def _on_deleted(_n):
            # 记录删除墓碑：无论服务器是否删除成功，都标记 message_id，
            # 防止定时拉取时把这些邮件重新同步回来。
            if message_ids:
                MailCacheRepository.mark_deleted(message_ids)
            # 清本地缓存 + 刷新列表
            for eid in email_ids:
                MailCacheRepository.delete(eid)
            self.mail_widget.load_folder(self.mail_widget.current_folder)
            if _n > 0:
                if count == 1:
                    self.toast.show_success(tr("邮件已删除 ✓"))
                else:
                    self.toast.show_success(f"{tr('已删除')} {_n}/{count}{tr(' 封邮件 ✓')}")
            else:
                self.toast.show_success(
                    tr("已从本地移除（服务器上未找到，可能已删除）"))

        worker.deleted.connect(_on_deleted)
        worker.failed.connect(lambda r: self.toast.show_error(f"{tr('删除失败：')}{r}"))
        # 防 GC 销毁运行中线程（同 compose worker 模式）
        self._retired_mail_delete_workers = getattr(self, '_retired_mail_delete_workers', [])
        self._retired_mail_delete_workers.append(worker)
        self.toast.show_success(tr("正在删除…"), 2000)
        worker.start()

    def _on_send_mail(self, mail_msg):
        """异步发送邮件（V1.4：使用 MailComposeSendWorker 后台发送）。"""
        from shadowtalk.ui.threads.mail_compose_send_worker import MailComposeSendWorker

        mail_config = {
            "host": Settings.get("mail_smtp_host"),
            "port": Settings.get_int("mail_smtp_port"),
            "use_tls": Settings.get_bool("mail_smtp_use_tls"),
            "username": Settings.get("mail_smtp_user"),
            "password": Settings.get("mail_smtp_password"),
        }
        if not mail_config["host"]:
            self.status_bar.showMessage(tr("请先在设置中配置 SMTP 服务器"), 6000)
            return
        # 安全警告：未启用 TLS 且非本机时，明文传输密码/内容
        if not mail_config["use_tls"] and not mail_config["host"].startswith("127.0.0.1"):
            reply = QMessageBox.warning(
                self, tr("安全警告"),
                tr("当前未启用 TLS 加密，邮件内容（含密码）将以明文传输。\n仍要发送？"),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        worker = MailComposeSendWorker(mail_msg, mail_config)
        # 发送结果用 Toast 顶部弹窗反馈（比状态栏小字更醒目）：成功绿色、失败红色
        def _on_sent():
            self.toast.show_success(tr("邮件已发送 ✓"))
            # 收件人进常用联系人（发出的 To 与收到的 From 同等重要）
            from shadowtalk.data.repositories import MailContactRepository
            MailContactRepository.add_sent_contact(mail_msg.to)
        worker.sent.connect(_on_sent)
        worker.failed.connect(lambda r: self.toast.show_error(f"{tr('发送失败：')}{r}"))
        # 防 GC 销毁运行中线程：保留引用，发送完成后无需主动移除（窗口关闭时统一清理）
        self._retired_mail_compose_workers = getattr(self, '_retired_mail_compose_workers', [])
        self._retired_mail_compose_workers.append(worker)
        self.status_bar.showMessage(tr("正在发送…"))
        worker.start()

    def _get_ai_client(self) -> AIClient:
        if self.ai_client is None:
            self.ai_client = AIClient(
                base_url=Settings.get("api_base_url"),
                api_key=Settings.get("api_key"),
                model=Settings.get("model_name"),
                temperature=Settings.get_float("temperature"),
                max_tokens=Settings.get_int("max_output_tokens"),
            )
        return self.ai_client

    def _stop_current_worker(self):
        """中断在途 AI 任务（用户发新消息时调用，间接撤销卡死的旧任务）

        terminate() 后 QThread 不会发出 finished 信号，且运行中的线程
        被 GC 会崩溃（"QThread: Destroyed while thread is still running"）。
        因此：断开其信号 → cancel → wait 短暂等待，仍运行则转入保留列表，
        由线程实际结束后安全析构。
        """
        w = self.ai_worker
        if w is None:
            return
        # 断开信号：terminate 后线程不会发 finished，但卡在 QEventLoop
        # 审批的旧 worker 可能仍会 emit；断开后迟到信号不再触发任何处理。
        # 无参 disconnect() 移除全部连接；对空信号 libpyside 会发
        # RuntimeWarning（不抛错），本地过滤掉以免刷日志。
        import warnings
        for sig in ("finished", "failed", "approval_requested", "activity"):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Failed to disconnect.*")
                try:
                    getattr(w, sig).disconnect()
                except RuntimeError:
                    pass  # C++ 对象已销毁
        w.cancel()
        if not w.wait(200):
            self._retired_workers.append(w)
        self.ai_worker = None
        self.chat_area.remove_approval_card()

    def closeEvent(self, event):
        """窗口关闭前：终止并等待在途 worker，避免 QThread 运行中销毁崩溃。"""
        # 邮件拉取 worker
        for w in getattr(self, '_retired_mail_fetch_workers', []):
            w.cancel()
            w.wait(500)
        # 写信发送 worker（V1.4 异步发送）
        for w in getattr(self, '_retired_mail_compose_workers', []):
            w.cancel()
            w.wait(500)
        # 邮件删除 worker（IMAP 删除不可中断，仅短暂等待）
        for w in getattr(self, '_retired_mail_delete_workers', []):
            w.wait(500)
        # AI 在途 worker
        self._stop_current_worker()
        for w in getattr(self, '_retired_workers', []):
            w.wait(500)
        super().closeEvent(event)

    def _on_message_sent(self, text: str):
        if not self.current_friend_id:
            return

        # 冻结态守卫：已授权作废的分身拒绝发送
        friend = FriendRepository.get_by_id(self.current_friend_id)
        if friend and friend["asset_revoked"]:
            QMessageBox.warning(self, tr("提示"), tr("该分身已被创作者取消授权，无法继续聊天"))
            return

        # 新消息直接中断上一个任务（用户：可间接撤销卡死的旧任务）
        self._stop_current_worker()

        ts = _now_timestamp()
        # 先插入 DB 拿到 msg_id，再渲染气泡（避免 msg_id 全为 0 导致语音按钮错位）
        msg_id = MessageRepository.insert(
            self.current_friend_id, "user", text,
            self._next_round_index(self.current_friend_id)
        )
        self.chat_area.add_message(text, "user", ts, msg_id)

        # 更新会话列表预览
        self.friend_list.set_last_message(
            self.current_friend_id,
            text[:30],
            ts[-5:]  # 只取 HH:MM
        )

        # ── 构建上下文并暂存（供日志记录用） ──
        try:
            context = build_context(self.current_friend_id, text)
            self._pending_context = context
            friend = FriendRepository.get_by_id(self.current_friend_id)
            self._pending_friend_name = (friend["remark"] or friend["name"]) if friend else tr("未知")
        except Exception as e:
            self._pending_context = None
            logger.error("构建上下文失败: %s", e, exc_info=True)
            context = None

        logger.info("发消息: 好友=%s 长度=%d", self._pending_friend_name, len(text))
        self.chat_area.show_loading()
        try:
            ai_client = self._get_ai_client()
        except Exception as e:
            self.chat_area.hide_loading()
            self.chat_area.add_message(f"AI 客户端初始化失败：{e}", "ai", ts)
            self._pending_context = None
            return

        friend = FriendRepository.get_by_id(self.current_friend_id)
        friend_work_dir = friend["work_dir"] if friend else ""
        self.ai_worker = AIWorker(
            self.current_friend_id, text,
            ai_client, self._pending_context or context,
            work_dir=friend_work_dir,
            approval_answered=self.approval_answered,
        )
        self.ai_worker.finished.connect(self._on_ai_reply)
        self.ai_worker.failed.connect(self._on_ai_failed)
        self.ai_worker.approval_requested.connect(self._on_approval_requested)
        self.ai_worker.activity.connect(self.chat_area.update_activity)
        self.ai_worker.start()

    def _on_ai_reply(self, reply: str):
        self.chat_area.hide_loading()
        ts = _now_timestamp()

        # 归因日志：写回原好友的场景同样可见，须在 stale 守卫之前记录
        worker = self.sender()
        friend_id = worker.friend_id if worker is not None else self.current_friend_id
        logger.info("AI 回复: 好友_id=%s 长度=%d", friend_id, len(reply))

        # 用户已切换/删除好友：回复只写回原好友，不显示在当前视图
        if worker is not None and worker.friend_id != self.current_friend_id:
            if FriendRepository.get_by_id(worker.friend_id) is None:
                return  # 好友已删除，丢弃回复，避免孤立消息
            MessageRepository.insert(
                worker.friend_id, "ai", reply,
                self._current_round_index(worker.friend_id)
            )
            self.friend_list.set_last_message(
                worker.friend_id, reply[:30], ts[-5:]
            )
            return

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

        # ── 记录提示词日志 ──
        if self._pending_context:
            user_msg = ""
            # 从上下文中提取最后一条 user 消息（即用户刚发的）
            for m in reversed(self._pending_context):
                if m.get("role") == "user" and m.get("layer") is None:
                    user_msg = m.get("content", "")
                    break
            if not user_msg and self.ai_worker:
                user_msg = self.ai_worker.user_message

            log_path = log_conversation(
                friend_name=self._pending_friend_name,
                friend_id=self.current_friend_id,
                context=self._pending_context,
                user_message=user_msg,
                ai_reply=reply,
            )
            if log_path:
                print(f"[PromptLogger] 日志已写入: {log_path}")

            self._pending_context = None

    def _on_ai_failed(self, error: str):
        worker = self.sender()
        friend_id = worker.friend_id if worker is not None else self.current_friend_id
        logger.error("AI 回复失败: 好友_id=%s 错误=%s", friend_id, error)
        self.chat_area.hide_loading()
        if worker is not None and worker.friend_id != self.current_friend_id:
            return  # 旧好友的失败提示不显示在当前视图
        self.chat_area.add_message(f"{tr('回复失败：')}{error}", "ai", _now_timestamp())

    def _on_status_message(self, msg: str):
        self.status_bar.showMessage(msg, 6000)

    def _on_approval_requested(self, code, paths, reason):
        """AI 请求目录外写入 → 弹出确认卡片"""
        self.chat_area.show_approval_card(paths, reason, self.approval_answered)

    def _on_approval_answered(self, allowed: bool):
        """确认卡片结果 → AIWorker 的 QEventLoop 收到"""
        pass  # 实际由卡片直接 emit 到 worker 的 approval_answered

    def _next_round_index(self, friend_id: int) -> int:
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return (row[0] or 0) + 1

    def _current_round_index(self, friend_id: int) -> int:
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return row[0] or 1
