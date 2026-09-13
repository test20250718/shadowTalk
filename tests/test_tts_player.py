"""TtsPlayer 状态机测试：不触网、不发声、不落盘，TtsWorker 用桩替换"""
import sys

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from shadowtalk.ui.widgets import tts_player as tts_player_module
from shadowtalk.ui.widgets.tts_player import TtsPlayer


class FakeWorker(QObject):
    """桩：start() 不发信号；由测试手动 emit_success() 模拟结果到达（回吐 bytes）"""
    succeeded = Signal(bytes, int)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, text, voice, msg_id):
        super().__init__()
        self._text = text
        self._msg_id = msg_id

    def start(self):
        pass

    def emit_success(self, data=b"mp3"):
        self.succeeded.emit(data, self._msg_id)


class FailingWorker(QObject):
    succeeded = Signal(bytes, int)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, text, voice, msg_id):
        super().__init__()
        self._msg_id = msg_id

    def start(self):
        self.failed.emit(self._msg_id, "network down")


@pytest.fixture()
def isolated(monkeypatch):
    """隔离：worker 桩 + 不碰真实音频设备"""
    monkeypatch.setattr(tts_player_module, "TtsWorker", FakeWorker)
    # 记录"开始播放"调用，替代真实音频
    started = []

    def fake_start(data, mid):
        started.append(mid)

    return started, fake_start


def make_player(fake_start):
    p = TtsPlayer()
    p._start_media = fake_start
    return p


def test_play_empty_text_noop(isolated):
    started, fake_start = isolated
    p = make_player(fake_start)
    p.play("   ", "zh-CN-XiaoxiaoNeural", 1)
    assert started == []
    assert p._worker is None


def test_worker_failure_emits_synthesis_failed(isolated, monkeypatch):
    started, fake_start = isolated
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
    started, fake_start = isolated
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


def test_play_cleans_markdown_before_synth(isolated):
    """回归：合成前去除 markdown 符号（* # 等不得被朗读）"""
    started, fake_start = isolated
    p = make_player(fake_start)
    p.play("**你好** *世界*", "zh-CN-XiaoxiaoNeural", 5)
    assert p._worker._text == "你好 世界"


def test_empty_synthesis_data_treated_as_failure(isolated):
    """合成返回空 bytes → 当作播放失败（避免 QBuffer 空数据卡死）"""
    started, fake_start = isolated
    p = make_player(fake_start)
    failed = []
    p.playback_failed.connect(lambda mid: failed.append(mid))
    p.play("你好", "zh-CN-XiaoxiaoNeural", 3)
    p._worker.emit_success(data=b"")  # 空数据
    assert failed == [3]
    assert started == []


def test_retired_worker_retained_until_finished(isolated):
    """打断后旧 worker 必须被保留（防"QThread: Destroyed while thread is still running"），
    finished 后从保留列表移除"""
    started, fake_start = isolated
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
