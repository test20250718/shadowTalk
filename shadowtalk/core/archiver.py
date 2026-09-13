# shadowtalk/core/archiver.py
import logging

from shadowtalk.data.repositories import MessageRepository, SummaryRepository
from shadowtalk.config.settings import Settings
from shadowtalk.core import summarizer

logger = logging.getLogger(__name__)


def check_and_archive(friend_id: int):
    """检查是否需要打包归档"""
    raw_keep_max = Settings.get_int("raw_keep_max")
    batch_size = Settings.get_int("summary_batch_size")

    raw_count = MessageRepository.count_unarchived_rounds(friend_id)

    if raw_count <= raw_keep_max:
        return

    overflow = raw_count - raw_keep_max
    buffer = MessageRepository.get_oldest_unarchived(friend_id, overflow)

    if len(buffer) < batch_size:
        return

    to_archive = buffer[:batch_size]
    # 摘要生成失败（AI 不可用）时跳过本轮归档，下条消息再试——
    # 不能把原文标记归档却只留下失败占位符
    try:
        summarizer.generate_batch_summary(friend_id, to_archive)
    except summarizer.SummaryGenerationError as e:
        logger.warning("批次摘要生成失败，跳过本轮归档 friend_id=%s：%s",
                       friend_id, e)
