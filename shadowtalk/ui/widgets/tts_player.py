"""
TTS 播放器：QMediaPlayer 单例，同时只服务一条语音。
新 play() 打断旧的（旧合成线程结果按 msg_id 失配丢弃）。

合成结果以 bytes 流经 QBuffer 播放，全程不落盘（无 tts_cache 累积）。
"""
import logging

from PySide6.QtCore import QObject, Signal, QBuffer, QByteArray, QIODeviceBase
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from shadowtalk.core.tts_service import clean_tts_text
from shadowtalk.ui.threads.tts_worker import TtsWorker


logger = logging.getLogger(__name__)


class TtsPlayer(QObject):
    playback_started = Signal(int)    # msg_id
    playback_finished = Signal(int)   # msg_id
    playback_failed = Signal(int)     # msg_id
    synthesis_failed = Signal(int)    # msg_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_media_error)
        self._worker = None      # 当前合成线程（只保留最新）
        self._retired = []       # 在途旧 worker 保留列表（防 QThread 运行中销毁）
        self._current_msg_id = None
        self._buffer = None      # 当前播放用的 QBuffer（保活，防被 GC）

    # ── 对外接口 ──
    def play(self, text: str, voice: str, msg_id: int):
        """播放文本。空文本忽略；打断当前播放/合成。"""
        text = clean_tts_text(text)  # 去 markdown 符号（* # 等不得被朗读）
        if not text or not text.strip():
            return
        self.stop()
        self._current_msg_id = msg_id
        # 合成走内存：worker 回吐 bytes → QBuffer → QMediaPlayer
        self._worker = TtsWorker(text, voice, msg_id)
        self._worker.succeeded.connect(self._on_worker_succeeded)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def stop(self):
        """停止播放并丢弃当前合成任务的结果"""
        self._stop_media()
        self._retire_worker()
        self._current_msg_id = None

    def _retire_worker(self):
        """当前 worker 转入保留列表：旧线程可能仍在合成（网络调用），
        直接释放引用会被 CPython 立即 GC，导致运行中的 QThread 被销毁
        （"QThread: Destroyed while thread is still running"，Windows 下可崩溃）。
        保留至 finished 信号后由 _on_worker_finished 移除。"""
        if self._worker is not None:
            self._retired.append(self._worker)
            self._worker = None

    def _on_worker_finished(self):
        """线程结束 → 从保留列表移除，允许安全析构"""
        w = self.sender()
        if w in self._retired:
            self._retired.remove(w)

    # ── 内部：音频 ──
    def _start_media(self, data: bytes, msg_id: int):
        # QBuffer 以 QByteArray(data) 构造（setData 写法会让 FFmpeg 后端
        # 探测不到 MP3 编解码参数 → 0 channels / 无声），不传 URL hint，
        # 让后端从 buffer 内容直接探测格式。_buffer 必须保活到下次替换。
        self._byte_array = QByteArray(data)
        self._buffer = QBuffer(self._byte_array)
        self._buffer.open(QIODeviceBase.ReadOnly)
        self._player.setSourceDevice(self._buffer)
        self._player.play()
        self._current_msg_id = msg_id
        self.playback_started.emit(msg_id)

    def _stop_media(self):
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        self._player.setSourceDevice(None)
        self._buffer = None

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            mid = self._current_msg_id
            self._current_msg_id = None
            self.playback_finished.emit(mid)

    def _on_media_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return
        mid = self._current_msg_id
        self._current_msg_id = None
        logger.error("TTS 播放失败: msg_id=%s 错误=%s", mid, error_string)
        self.playback_failed.emit(mid)

    # ── 内部：合成线程结果 ──
    def _on_worker_succeeded(self, data: bytes, msg_id: int):
        if msg_id != self._current_msg_id:
            return  # stale：已被更新的播放请求打断
        if not data:
            # 合成返回空（异常兜底）→ 当作失败，避免 QBuffer 空数据卡死
            self._on_media_error(QMediaPlayer.Error.FormatError, "empty audio")
            return
        self._start_media(data, msg_id)

    def _on_worker_failed(self, msg_id: int, error: str):
        if msg_id != self._current_msg_id:
            return  # stale
        self._current_msg_id = None
        self.synthesis_failed.emit(msg_id)


_player_instance = None


def get_player() -> TtsPlayer:
    """懒加载单例：QMediaPlayer 构造推迟到首次使用。

    注意：main.py / test_main_window.py 在创建 QApplication 之前就
    import MainWindow（模块级），若在模块级直接构造 QMediaPlayer/
    QAudioOutput 会因 QApplication 缺失而初始化失败。首次调用时
    QApplication 必然已存在（ChatArea 只在 app 创建后实例化）。
    """
    global _player_instance
    if _player_instance is None:
        _player_instance = TtsPlayer()
    return _player_instance
