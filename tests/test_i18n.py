"""i18n 国际化管理器测试。"""
import sys
import json
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from shadowtalk.config.i18n import (
    load, tr, set_language, on_language_changed, language, LANGUAGES,
)

app = QApplication.instance() or QApplication(sys.argv)


def _write_lang(tmpdir: Path):
    """写入测试用翻译文件。"""
    (tmpdir / "resources" / "lang").mkdir(parents=True, exist_ok=True)
    zh = {"设置": "设置", "帮助": "帮助"}
    en = {"设置": "Settings", "帮助": "Help", "关于": "About"}
    (tmpdir / "resources" / "lang" / "zh.json").write_text(
        json.dumps(zh), encoding="utf-8")
    (tmpdir / "resources" / "lang" / "en.json").write_text(
        json.dumps(en), encoding="utf-8")


def test_tr_falls_back_to_source():
    """无译文时回退到源语言字符串（中文）。"""
    from shadowtalk.config import i18n
    # 模拟：当前语言英文，"关于" 在 en.json 里有
    i18n._lang = "en"
    i18n._translations = {
        "en": {"设置": "Settings", "关于": "About"},
        "zh": {},
    }
    assert tr("设置") == "Settings"
    # "帮助" 在英文里没有 → 回退到中文 key
    assert tr("帮助") == "帮助"


def test_set_language_notifies_listeners(monkeypatch):
    """切换语言应通知所有注册的回调。"""
    from shadowtalk.config import i18n
    i18n._translations = {"en": {}, "zh": {}}
    i18n._lang = "zh"
    i18n._listeners = []

    calls = []
    on_language_changed(lambda: calls.append(1))
    on_language_changed(lambda: calls.append(2))

    # 模拟 Settings.set（忽略写入）
    monkeypatch.setattr("shadowtalk.config.i18n.Settings.set",
                        lambda k, v: None)

    set_language("en")

    assert language() == "en"
    assert calls == [1, 2]


def test_set_language_ignores_invalid(monkeypatch):
    """无效语言代码应被忽略。"""
    from shadowtalk.config import i18n
    i18n._lang = "zh"
    i18n._listeners = []
    monkeypatch.setattr("shadowtalk.config.i18n.Settings.set",
                        lambda k, v: None)

    set_language("fr")
    assert language() == "zh"  # 不变

    # 切换到相同语言也不触发
    calls = []
    on_language_changed(lambda: calls.append(1))
    set_language("zh")
    assert calls == []


def test_languages_defined():
    """支持的语言应包含中英文。"""
    assert "zh" in LANGUAGES
    assert "en" in LANGUAGES
