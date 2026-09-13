# shadowtalk/core/tts_service.py
"""
TTS 语音合成服务（纯 Python，禁止 import PySide6）

职责：音色清单、音色解析、edge-tts 合成、本地音频缓存。
播放（QtMultimedia）在 ui 层，见 ui/widgets/tts_player.py。
"""
import asyncio
import io
import logging
import re
from pathlib import Path

# 数据根目录 —— 与 config.paths.get_base_dir() 保持一致：
# 开发时 cwd()；Windows 打包后 exe 所在目录；Linux 打包后 ~/.shadowtalk
import sys
if getattr(sys, "frozen", False) and sys.platform != "win32":
    _BASE_DIR = Path.home() / ".shadowtalk"
elif getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path.cwd()

logger = logging.getLogger(__name__)

TTS_VOICES = [
    {"label": "晓晓（女·温柔）", "voice": "zh-CN-XiaoxiaoNeural"},
    {"label": "云希（男·阳光）", "voice": "zh-CN-YunxiNeural"},
    {"label": "晓伊（女·活泼）", "voice": "zh-CN-XiaoyiNeural"},
    {"label": "云扬（男·新闻）", "voice": "zh-CN-YunyangNeural"},
    {"label": "晓辰（女·青春）", "voice": "zh-CN-XiaochenNeural"},
    {"label": "云健（男·沉稳）", "voice": "zh-CN-YunjianNeural"},
    {"label": "Aria（英·女）", "voice": "en-US-AriaNeural"},
    {"label": "Guy（英·男）", "voice": "en-US-GuyNeural"},
]

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_IDS = {v["voice"] for v in TTS_VOICES}

# 表情与装饰符号（不朗读）：emoji 各区块、印刷符号（✓✔✗）、
# 杂项符号（☀☎）、几何形状（●○■◆）、制表框线、变体选择符、ZWJ。
# 不含：CJK 标点、全角标点、General Punctuation（“”—…）、×÷ 等算术符。
_EMOJI_SYMBOL_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # 扩展表情（含 🎉😊➡🅰 及旗帜）
    "\U00002600-\U000027BF"   # 杂项符号 + 印刷符号（✓✔✗✂✈❤）
    "\U00002B00-\U00002BFF"   # 杂项符号与箭头（⭐）
    "\U00002500-\U0000257F"   # 制表符（ASCII 表格框线）
    "\U000025A0-\U000025FF"   # 几何形状（●○■□◆◇）
    "\U0000FE00-\U0000FE0F"   # 变体选择符（❤️ 的 FE0F）
    "\U0000200D"              # 零宽连接符（组合 emoji）
    "\U000020E3"              # 组合用包围键帽
    "]+"
)


def resolve_voice(friend_voice: str, global_voice: str) -> str:
    """音色解析：好友指定 > 全局默认 > 兜底"""
    if friend_voice in VOICE_IDS:
        return friend_voice
    if global_voice in VOICE_IDS:
        return global_voice
    return DEFAULT_VOICE


def clean_tts_text(text: str) -> str:
    """朗读前清洗：去除 markdown 符号（* # ` | 等），只留口语化正文。

    代码块整段删除（朗读无意义且会念出符号）；加粗/斜体/链接/表格
    符号去除、保留文字；普通标点与单星号（如 2*3=6）保留。
    """
    if not text:
        return ""
    # 代码块（整段删除）
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    # 图片/链接：保留说明文字
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # 行内代码
    text = re.sub(r"`([^`]*)`", r"\1", text)
    # 行首标记：标题 / 引用 / 无序列表 / 有序列表
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^>\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+[.、)]\s*", "", text, flags=re.M)
    # 表格分隔线行（|---|、|:--:|）
    text = re.sub(r"^\s*\|[\s:|-]+\|\s*$", "", text, flags=re.M)
    # 加粗 / 下划线加粗 / 斜体 / 下划线斜体 / 删除线（先双后单）
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # 表情与装饰符号：✓✔ emoji ●○ 等不得被朗读
    text = _EMOJI_SYMBOL_RE.sub(" ", text)
    # 表格单元格分隔与纯分隔线
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.M)
    # 空白折叠
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def synthesize(text: str, voice: str, out_path) -> None:
    """将文本合成为 MP3 写入 out_path。空文本直接返回。

    edge_tts 惰性导入：即使包缺失，import 本模块也不失败，
    仅在真正合成时抛 ImportError（由 ui 层统一提示失败）。
    """
    if not text or not text.strip():
        return
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    communicate.save_sync(str(out_path))


def synthesize_bytes(text: str, voice: str) -> bytes:
    """将文本合成为 MP3 并以 bytes 返回（不落盘）。

    直接驱动 edge_tts 的 stream() 写入 BytesIO，避免任何磁盘 IO。
    空文本返回 b""。
    """
    if not text or not text.strip():
        return b""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()

    async def _run():
        async for message in communicate.stream():
            if message["type"] == "audio":
                buf.write(message["data"])

    asyncio.run(_run())
    return buf.getvalue()


