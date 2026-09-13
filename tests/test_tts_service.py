# tests/test_tts_service.py
import sys
from pathlib import Path

import pytest

from shadowtalk.core import tts_service
from shadowtalk.core.tts_service import (
    DEFAULT_VOICE, TTS_VOICES, VOICE_IDS, clean_tts_text,
    resolve_voice, synthesize, synthesize_bytes,
)


def test_voice_list_contains_default():
    assert DEFAULT_VOICE in VOICE_IDS
    assert len(TTS_VOICES) >= 8
    for v in TTS_VOICES:
        assert set(v) == {"label", "voice"}
        assert v["voice"] in VOICE_IDS


def test_resolve_voice_friend_wins():
    assert resolve_voice("zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural") == "zh-CN-YunxiNeural"


def test_resolve_voice_global_fallback():
    # 好友音色非法 → 用全局
    assert resolve_voice("no-such-voice", "zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"
    # 好友为空 → 用全局
    assert resolve_voice("", "zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"


def test_resolve_voice_default_fallback():
    assert resolve_voice("bad", "worse") == DEFAULT_VOICE


def test_synthesize_empty_text_no_call(tmp_path, monkeypatch):
    called = []
    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text, self.voice = text, voice
        def save_sync(self, path):
            called.append((self.text, self.voice, path))
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    synthesize("   ", "zh-CN-XiaoxiaoNeural", tmp_path / "x.mp3")
    assert called == []


def test_synthesize_calls_edge_tts(tmp_path, monkeypatch):
    seen = {}
    class FakeCommunicate:
        def __init__(self, text, voice):
            seen["text"], seen["voice"] = text, voice
        def save_sync(self, path):
            seen["path"] = path
            Path(path).write_bytes(b"mp3")
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    out = tmp_path / "out.mp3"
    synthesize("你好", "zh-CN-XiaoxiaoNeural", out)
    assert seen == {"text": "你好", "voice": "zh-CN-XiaoxiaoNeural", "path": str(out)}
    assert out.read_bytes() == b"mp3"


def test_synthesize_bytes_empty_text_no_call(monkeypatch):
    called = []
    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text, self.voice = text, voice
        def stream(self):
            called.append((self.text, self.voice))
            # 异步生成器：必须 yield 才构成 async iterable，但此处不应被消费
            return
            yield
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    assert synthesize_bytes("   ", "zh-CN-XiaoxiaoNeural") == b""
    assert called == []


def test_synthesize_bytes_collects_audio(monkeypatch):
    """stream() 回吐的音频 chunk 必须被完整收集到返回的 bytes 中"""
    chunks = [b"aaa", b"bbb", b"ccc"]
    class FakeCommunicate:
        def __init__(self, text, voice):
            pass
        async def stream(self):
            for c in chunks:
                yield {"type": "audio", "data": c}
    monkeypatch.setitem(sys.modules, "edge_tts", type("edge_tts", (), {"Communicate": FakeCommunicate})())
    assert synthesize_bytes("你好", "zh-CN-XiaoxiaoNeural") == b"aaabbbccc"


def test_clean_tts_text_strips_markdown_symbols():
    """回归：朗读不得念出 markdown 符号（* # ` 等），保留正文"""
    assert clean_tts_text("**加粗** 和 *斜体*") == "加粗 和 斜体"
    assert clean_tts_text("~~删除线~~ 和 __下划线__") == "删除线 和 下划线"
    assert clean_tts_text("# 大标题") == "大标题"
    assert clean_tts_text("> 引用内容") == "引用内容"
    assert clean_tts_text("- 列表项一\n- 列表项二") == "列表项一\n列表项二"
    assert clean_tts_text("1. 第一\n2. 第二") == "第一\n第二"
    assert clean_tts_text("`inline code`") == "inline code"
    assert clean_tts_text("[链接文字](https://example.com)") == "链接文字"
    assert clean_tts_text("![图片说明](img.png)") == "图片说明"
    assert clean_tts_text("普通文本，没有符号 2*3=6") == "普通文本，没有符号 2*3=6"


def test_clean_tts_text_drops_code_blocks_and_table_bars():
    """代码块整段删除（朗读无意义）；表格竖线去除"""
    assert clean_tts_text("```python\nprint(1)\n```\n正文") == "正文"
    text = "| 名称 | 值 |\n|---|---|\n| a | 1 |"
    out = clean_tts_text(text)
    assert "|" not in out
    assert "-" not in out
    assert "名称" in out and "1" in out


def test_clean_tts_text_strips_emoji_and_symbols():
    """回归（用户报告）：对勾 ✓✔、emoji、圆点等符号不得进入朗读"""
    assert clean_tts_text("任务完成 ✓ 请查收") == "任务完成 请查收"
    assert clean_tts_text("完成了 ✔✔") == "完成了"
    assert clean_tts_text("你好 😊 很高兴") == "你好 很高兴"
    assert clean_tts_text("庆祝一下 🎉✨ 不错") == "庆祝一下 不错"
    assert clean_tts_text("❤️ 喜欢吗") == "喜欢吗"


def test_clean_tts_text_strips_bullet_shapes():
    """几何符号列表点 ●○■◆ 与制表框线不朗读，保留文字"""
    assert clean_tts_text("● 重点\n○ 次要") == "重点\n次要"
    assert clean_tts_text("◆ 要点一则") == "要点一则"


def test_clean_tts_text_keeps_normal_punctuation_and_math():
    """清理不得误伤正常标点与算式（2×3=6 的乘号、百分号等保留）"""
    assert clean_tts_text("2×3=6，对吗？") == "2×3=6，对吗？"
    assert clean_tts_text("完成度 95%，加油！") == "完成度 95%，加油！"
