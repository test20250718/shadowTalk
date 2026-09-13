"""
ShadowTalk 左侧垂直图标 Tab 栏（微信式）
主窗口最左侧 50px 栏，两个图标按钮：聊天 / 邮箱。
点击切换时发射 tab_changed(index)，由 MainWindow 同步切换左右 QStackedWidget。
（联系人管理在邮箱页内部切换视图，不占独立 Tab）

图标用 QPainter 手绘矢量线稿，不用 emoji（用户反馈：邮箱 emoji 又小又难看）：
emoji 在 Windows 上经字体回退渲染，实际只有 ~13px、两枚图标视觉大小不一，
且颜色不跟随主题与选中态。矢量线稿 24px、线宽一致，未选中随主题变灰、
选中变白，高分屏按 2x 物理像素渲染保持清晰。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy
from PySide6.QtCore import Signal, Qt, QSize, QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QIcon, QPen, QBrush, QColor, QPolygonF
from shadowtalk.ui.theme import current as theme_current

# 两个 Tab 的绘制函数与提示（index 0 = 聊天，index 1 = 邮箱）
TAB_TIPS = ["聊天", "邮箱"]

BTN_SIZE = 40   # 图标按钮尺寸（50px 栏宽留 5px 内边距）
ICON_PX = 24    # 图标逻辑边长（40px 按钮内 24px 图标，四周各留 8px）
DPR = 2.0       # 物理像素倍率：2x 渲染，1x 屏幕平滑缩小、2x 屏幕原生清晰


def _draw_chat(p: QPainter, color: QColor):
    """聊天气泡：圆角气泡 + 左下小尾巴 + 三点（24x24 网格线稿）。

    尾巴视觉重量轻，眼睛以气泡体定位——整体下移 ~0.7px 做光学居中
    （截图复核：尾巴朝下的气泡若按几何居中会显得偏高）。
    """
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 5.2, 17, 12), 5, 5)
    p.drawPolyline(QPolygonF([
        QPointF(8.0, 16.9), QPointF(8.0, 20.4), QPointF(11.8, 16.9)]))
    # 三个填充圆点（会话感），无线框
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    for cx in (7.5, 12.0, 16.5):
        p.drawEllipse(QPointF(cx, 11.2), 1.1, 1.1)


def _draw_mail(p: QPainter, color: QColor):
    """信封：圆角信封体 + 折线封盖（24x24 网格线稿）。

    信封比气泡矮且线条少，同网格下光学尺寸偏小——加宽加高到近满格，
    且线宽 2.0（比气泡粗 0.2）：灰线在浅底上因同时对比效应显细，
    白线在绿底上显粗，同宽会不等重（截图复核发现的重量差）。
    """
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.8, 5.0, 18.4, 14), 2.2, 2.2)
    p.drawPolyline(QPolygonF([
        QPointF(3.8, 6.4), QPointF(12.0, 13.6), QPointF(20.2, 6.4)]))


_DRAWERS = [_draw_chat, _draw_mail]


def _pixmap(draw_fn, color: QColor) -> QPixmap:
    """在 24x24 逻辑画布上绘制线稿（2x 物理分辨率）。"""
    pm = QPixmap(int(ICON_PX * DPR), int(ICON_PX * DPR))
    pm.setDevicePixelRatio(DPR)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_fn(p, color)
    p.end()
    return pm


def make_tab_icon(index: int, base_color) -> QIcon:
    """生成 Tab 图标：未选中 = 主题灰线稿；选中 = 白色线稿。

    QSS 的 color 只作用于文字不作用于图标像素，选中变白必须靠
    QIcon 的 On/Off 两态 pixmap 实现。
    """
    base = QColor(base_color)
    icon = QIcon()
    icon.addPixmap(_pixmap(_DRAWERS[index], base), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap(_DRAWERS[index], QColor("#FFFFFF")),
                   QIcon.Normal, QIcon.On)
    return icon


class VerticalTabBar(QWidget):
    """左侧垂直图标 Tab 栏，选中态 accent 底 + 白图标，未选中透明底 + muted 图标"""

    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons = []
        self._current_index = 0
        self._build_ui()

    def _build_ui(self):
        self.setFixedWidth(50)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 12, 5, 8)
        layout.setSpacing(8)
        for index, tip in enumerate(TAB_TIPS):
            btn = QPushButton()
            btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            btn.setIconSize(QSize(ICON_PX, ICON_PX))
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            # 用默认参数捕获 index，避免闭包绑定到循环变量
            btn.clicked.connect(lambda _=False, i=index: self._on_tab_clicked(i))
            self._buttons.append(btn)
            layout.addWidget(btn)
        # 底部撑开，让两个按钮靠顶
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # 默认选中第一个
        self.set_current(0)

    def _on_tab_clicked(self, index):
        """点击 Tab：仅当切换时才更新状态并发射信号（避免重复触发）"""
        if index == self._current_index:
            return
        self.set_current(index)
        self.tab_changed.emit(index)

    def set_current(self, index):
        """程序化切换 Tab（不发射信号，供 MainWindow 同步调用）"""
        self._current_index = index
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
        self._apply_styles()

    def _apply_styles(self):
        """按当前主题重设栏背景、按钮样式与图标颜色"""
        t = theme_current()
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {t.SURFACE};
                border-right: 1px solid {t.BORDER};
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
            }}
            QPushButton:checked {{
                background-color: {t.ACCENT};
            }}
        """)
        # 未选中图标颜色随主题变化，需随 restyle 重新生成
        for i, btn in enumerate(self._buttons):
            btn.setIcon(make_tab_icon(i, t.MUTED))

    def restyle(self):
        """主题切换后由 MainWindow 调用，重绘样式"""
        self._apply_styles()
