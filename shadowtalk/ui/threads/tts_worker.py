"""TTS 合成工作线程：edge-tts 网络合成不阻塞 UI（纯内存，不落盘）"""
import logging
from PySide6.QtCore import QThread, Signal

from shadowtalk.core.tts_service import synthesize_bytes


logger = logging.getLogger(__name__)


class TtsWorker(QThread):
    succeeded = Signal(bytes, int)  # (mp3_bytes, msg_id)
    failed = Signal(int, str)       # (msg_id, error)

    def __init__(self, text: str, voice: str, msg_id: int):
        super().__init__()
        self._text = text
        self._voice = voice
        self._msg_id = msg_id

    def run(self):
        try:
            data = synthesize_bytes(self._text, self._voice)
            self.succeeded.emit(data, self._msg_id)
        except Exception as e:
            logger.error("TTS 合成失败: msg_id=%s 错误=%s", self._msg_id, e)
            self.failed.emit(self._msg_id, str(e))
