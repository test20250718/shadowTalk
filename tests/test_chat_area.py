"""ChatArea loading 生命周期测试

回归保护：切换/删除好友时清空消息列表会导致 _loading_item 悬垂，
旧 AIWorker 回复到达时 hide_loading() 访问已删除的 C++ 对象而崩溃。
"""
import sys
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication
from shadowtalk.config.settings import Settings
from shadowtalk.ui.widgets.chat_area import ChatArea

app = QApplication.instance() or QApplication(sys.argv)


def test_restyle_reapplies_dark_theme_styles():
    """主题切换后 restyle() 将容器样式重设为深色（回归：构造时一次取色冻结）"""
    from shadowtalk.ui import theme
    area = ChatArea()
    theme.set_current("dark")
    area.restyle()
    assert "#1A1A1E" in area.styleSheet()                # DARK.BG
    assert "#26262B" in area._header.styleSheet()        # DARK.SURFACE
    assert "#4A4A52" in area.message_list.styleSheet()   # DARK.SCROLL_HANDLE
    assert "#34C274" in area.send_btn.styleSheet()       # DARK.ACCENT
    assert "#E8E6E1" in area.input_box.styleSheet()      # DARK.FG
    assert "#26262B" in area.emoji_panel.styleSheet()    # 持有的表情面板同步重设
    theme.set_current("light")  # 复位


def test_tts_toggle_exists_and_styled():
    """聊天头部语音开关按钮存在且已应用样式（主题切换已移至工具栏）"""
    area = ChatArea()
    assert area._tts_toggle is not None
    assert area._tts_toggle.text() in ("🔊", "🔇")


def test_clear_messages_resets_loading_state():
    """清空消息列表后 loading 状态必须复位，旧 worker 回复到达不再崩溃"""
    area = ChatArea()
    area.show_loading()
    assert area._loading_item is not None
    assert not area.send_btn.isEnabled()

    area.clear_messages()

    assert area._loading_item is None
    assert area.send_btn.isEnabled()
    # 模拟切换好友后旧 worker 的回复到达：不应抛 RuntimeError
    area.hide_loading()


def test_hide_loading_removes_loading_item():
    """正常路径：hide_loading 移除 loading 项并复位状态"""
    area = ChatArea()
    area.show_loading()
    count = area.message_list.count()
    assert count == 1

    area.hide_loading()

    assert area.message_list.count() == 0
    assert area._loading_item is None
    assert area.send_btn.isEnabled()


def test_show_loading_replaces_stale_loading_item():
    """中断场景：旧任务卡死时再次 loading 必须先移除旧项，
    否则列表里堆叠多个打字动画"""
    area = ChatArea()
    area.show_loading()
    first = area._loading_item

    area.show_loading()

    assert area.message_list.row(first) == -1  # 旧 loading 项已移除
    assert area._loading_item is not first


def test_remove_approval_card_removes_item():
    """中断旧任务时撤销展示中的审批确认卡片"""
    area = ChatArea()
    area.show_approval_card(["a.txt"], "测试", lambda _: None)
    assert area._approval_card is not None
    assert area.message_list.count() == 1

    area.remove_approval_card()

    assert area._approval_card is None
    assert area.message_list.count() == 0
    area.remove_approval_card()  # 幂等：已无卡片再调不崩


# ── 工作过程卡：AI 干活时显示当前步骤与耗时（用户：怕卡死）──

def test_update_activity_shows_text_in_loading_item():
    """loading 行内显示最新活动文字（执行工具：xxx）"""
    area = ChatArea()
    area.show_loading()
    area.update_activity("执行工具：生成天气报告")
    assert area._activity_label is not None
    assert "生成天气报告" in area._activity_label.text()
    assert area._activity_timer.isActive()


def test_update_activity_ignored_without_loading_item():
    """无 loading 项时收到活动信号（迟到/中断后）安全忽略"""
    area = ChatArea()
    area.update_activity("执行工具：x")  # 不崩
    assert area._activity_label is None


def test_hide_loading_clears_activity_state():
    """结果到达移除工作卡：活动文字清空、计时器停止并释放"""
    area = ChatArea()
    area.show_loading()
    area.update_activity("执行工具：x")
    area.hide_loading()
    assert area._activity_timer is None  # 已停止并释放（None = 不再计时）
    assert area._activity_label is None
    assert area._activity_text == ""


def test_show_loading_resets_activity_for_new_task():
    """新任务的工作卡不带上一轮的活动文字"""
    area = ChatArea()
    area.show_loading()
    area.update_activity("上一轮的活动")
    area.show_loading()  # 新任务
    assert area._activity_text == ""


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
    # 固化全局音色，保证断言不受运行时 DB 配置影响
    Settings.set("tts_voice", "zh-CN-XiaoxiaoNeural")
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


def test_long_message_bubble_not_clipped_at_wide_viewport():
    """回归：宽视口(1100px) + 3000 字长消息，气泡 QLabel 高度必须
    满足实际换行需求 —— 曾因 QLabel::heightForWidth 不按 maximumWidth
    截断传入宽度，item 高度按过宽(1000+px)计算而不足，尾部文字被裁剪"""
    area = ChatArea()
    area.resize(1100, 800)
    area.show()
    from PySide6.QtTest import QTest
    QTest.qWait(20)
    area.add_message("爱" * 3000, "user", "14:00", msg_id=1)
    QTest.qWait(20)
    item = area.message_list.item(0)
    bubble = area.message_list.itemWidget(item)
    sb = bubble._bubble
    # item 高度必须足够，QLabel 实高不小于其在该宽度下的需求高度
    assert item.sizeHint().height() >= 2500
    assert sb.height() >= sb.heightForWidth(sb.width()) - 1


def test_short_message_bubble_not_clipped():
    """回归：短文本(50字)气泡 QLabel 高度也要满足需求 —— 曾因 hfw
    链用 420px 计算、而布局实际按文本自然宽度(260px)分配导致低估 20px"""
    area = ChatArea()
    area.resize(772, 800)
    area.show()
    from PySide6.QtTest import QTest
    QTest.qWait(20)
    area.add_message("你好，今天天气不错。" * 5, "user", "14:00", msg_id=1)
    QTest.qWait(20)
    bubble = area.message_list.itemWidget(area.message_list.item(0))
    sb = bubble._bubble
    assert sb.height() >= sb.heightForWidth(sb.width()) - 1


def test_user_bubble_right_aligned_at_wide_viewport():
    """回归：最大化宽度下用户气泡必须靠右（微信风格）——
    曾因 meta_row 内的 stretch 使 bubble_col 水平可扩展，与外层
    stretch（因子 0）平分剩余空间，气泡漂到窗口中间"""
    area = ChatArea()
    area.resize(1400, 800)
    area.show()
    from PySide6.QtTest import QTest
    QTest.qWait(20)
    area.add_message("你好", "user", "14:00", msg_id=1)
    QTest.qWait(20)
    bubble = area.message_list.itemWidget(area.message_list.item(0))._bubble
    # 靠右时右侧仅剩 头像(32)+间距(10)+边距(26)=68px（允许少量布局余量）
    right_gap = area.message_list.viewport().width() - (bubble.x() + bubble.width())
    assert right_gap <= 120, f"用户气泡未靠右，右侧空隙 {right_gap}px"


def test_ai_bubble_width_follows_window_resize():
    """回归：窗口拉宽（如切全屏）后，已有 AI 气泡宽度必须跟随铺满——
    曾因 QListWidget 默认 Fixed 布局模式 + item sizeHint 只在插入时计算，
    以及 AI 气泡 AlignLeft 把宽度钉在 sizeHint，切全屏后气泡不铺满"""
    from PySide6.QtTest import QTest
    area = ChatArea()
    area.resize(800, 700)
    area.show()
    QTest.qWait(20)
    area.set_friend_info(1, "小美")
    area.add_message("这是一条比较长的AI消息，包含一些内容用于换行测试。" * 20,
                     "ai", "14:00", msg_id=1)
    QTest.qWait(20)
    lst = area.message_list
    ai_sb = lst.itemWidget(lst.item(0))._bubble
    w1 = ai_sb.width()
    assert w1 < lst.viewport().width()  # 初始未铺满时气泡小于视口

    area.resize(1400, 900)
    QTest.qWait(50)
    # AI 气泡应接近占满：视口宽 - 头像(32) - 间距(10) - 边距(52)
    expect = lst.viewport().width() - 94
    assert ai_sb.width() >= expect - 20, (
        f"拉宽后 AI 气泡未铺满: {ai_sb.width()} < {expect - 20}"
    )
    # 缩回窄窗口也要跟随缩小
    area.resize(700, 500)
    QTest.qWait(50)
    assert ai_sb.width() <= lst.viewport().width() - 80, "缩窄后 AI 气泡未跟随"


def test_set_friend_info_updates_header_avatar_name():
    """切换好友后头部头像应显示新好友（回归：曾只更新名称不更新头像）"""
    area = ChatArea()
    area.set_friend_info(1, "小美")
    assert area._header_avatar._name == "小美"
    assert area._header_avatar._pixmap is None  # 无头像文件 → 名字首字模式

    area.set_friend_info(2, "大宝")
    assert area._header_avatar._name == "大宝"


def test_set_friend_info_updates_header_avatar_image(tmp_path):
    """好友设了头像文件 → 头部头像加载图片"""
    img = tmp_path / "avatar.png"
    pix = QPixmap(24, 24)
    pix.fill(QColor("red"))
    assert pix.save(str(img))

    area = ChatArea()
    area.set_friend_info(1, "小美", str(img))
    assert area._header_avatar._name == "小美"
    assert area._header_avatar._pixmap is not None

    # 切换到无头像好友 → 回落名字首字
    area.set_friend_info(2, "大宝", "")
    assert area._header_avatar._pixmap is None
    assert area._header_avatar._name == "大宝"


def test_show_empty_state_hides_chat_ui():
    """无选中好友：头部/消息列表/输入区全部隐藏，聊天区空白（微信风格）"""
    area = ChatArea()
    assert not area._header.isHidden()
    assert not area._composer_wrap.isHidden()

    area.show_empty_state()
    assert area._header.isHidden()
    assert area.message_list.isHidden()
    assert area._composer_wrap.isHidden()

    area.show_conversation()
    assert not area._header.isHidden()
    assert not area.message_list.isHidden()
    assert not area._composer_wrap.isHidden()
