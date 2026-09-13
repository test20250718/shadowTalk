# shadowtalk/ui/threads/ai_worker.py
import logging
import time

from PySide6.QtCore import QThread, Signal

from shadowtalk.config.settings import Settings


logger = logging.getLogger(__name__)


class AIWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)
    approval_requested = Signal(str, list, str)  # (code, paths, reason)
    activity = Signal(str)   # 工作过程文字（思考/执行工具/完成，供工作卡显示）

    def __init__(self, friend_id, user_message, ai_client, messages: list,
                 work_dir: str = "", approval_answered=None):
        """
        Args:
            friend_id: 好友 ID
            user_message: 用户原始消息（用于日志）
            ai_client: AI 客户端实例
            messages: 已构建好的完整上下文（由 build_context 生成）
            work_dir: 工作目录；目录外写入需用户审批
            approval_answered: 审批结果信号（Signal(bool)），
                               None 时目录外写入一律拒绝
        """
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.ai_client = ai_client
        self.messages = messages
        self.work_dir = work_dir
        self._approval_answered = approval_answered
        self._approved = False
        # 干活限额（用户可调）：单轮工具调用上限、单次执行超时秒数
        self.max_tool_calls = Settings.get_int("max_tool_calls")
        self.tool_timeout = Settings.get_int("tool_timeout")

    def cancel(self):
        """强制中断在途任务。

        openai 同步调用无超时、工具执行也无超时，无法协作式取消，
        只能 terminate()。terminate 后不会发出 finished/failed 信号，
        由调用方（MainWindow._stop_current_worker）断开信号并保留引用。
        """
        if self.isRunning():
            self.terminate()

    def run(self):
        try:
            self.activity.emit("正在思考…")
            reply = self.ai_client.chat_with_tools(
                self.messages,
                tool_runner=self._run_tool,
                max_tool_calls=self.max_tool_calls,
            )
            self.finished.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))

    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码；未配置工作目录时拒绝，目录外写需经 UI 审批。"""
        if not self.work_dir:
            # 未配置工作目录：拒绝执行，避免写入当前进程目录
            logger.warning("拒绝工具执行: 未配置工作目录")
            return ("当前好友未配置工作目录。请在好友设置中添加工作目录，"
                    "即可让我读写文件。")

        self.activity.emit(f"执行工具：{reason or code[:20]}")
        start = time.time()
        result = self._execute_tool(code, reason)
        self.activity.emit(f"工具完成（{time.time() - start:.1f} 秒），继续思考…")
        return result

    def _execute_tool(self, code: str, reason: str) -> str:
        """审批与执行（由 _run_tool 调用，activity 已在外层报告）"""
        logger.info("执行工具: reason=%s", reason)

        from shadowtalk.core.python_executor import (
            run_with_approval, scan_write_paths,
        )

        outside_paths = scan_write_paths(code, self.work_dir)
        # 目录内写入无需审批，直接执行
        if not outside_paths:
            return run_with_approval(
                code, self.work_dir,
                approver=lambda paths, r: True, reason=reason,
                timeout=self.tool_timeout,
            ).summary()

        # 有目录外写入：无 UI 可审批 → 拒绝
        if not self._approval_answered:
            return run_with_approval(
                code, self.work_dir,
                approver=lambda paths, r: False, reason=reason,
                timeout=self.tool_timeout,
            ).summary()

        from PySide6.QtCore import QEventLoop

        loop = QEventLoop()

        def on_answer(allowed: bool):
            loop.quit()
            self._approved = allowed

        self._approved = False
        self.approval_requested.emit(code, outside_paths, reason)  # 发到主线程
        self._approval_answered.connect(on_answer)
        loop.exec()  # 嵌套事件循环，等待用户点击
        self._approval_answered.disconnect(on_answer)
        return run_with_approval(
            code, self.work_dir,
            approver=lambda paths, r: self._approved,
            reason=reason,
            timeout=self.tool_timeout,
        ).summary()
