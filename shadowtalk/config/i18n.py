# shadowtalk/config/i18n.py
"""轻量国际化（i18n）管理器。

设计：
- 以模块级全局状态运作（类似 theme.py），无 Qt 依赖，core/data 层可安全 import。
- 以源语言（中文）字符串为 key，目标语言 JSON 提供译文；
  当前语言无译文时回退到 key 本身（即中文），保证翻译不完整也能正常显示。
- 语言切换时回调所有已注册的 listener，各 UI 组件自行刷新显示文本。

用法：
    from shadowtalk.config.i18n import tr
    label.setText(tr("设置"))            # 中文→"设置"，英文→"Settings"
    on_language_changed.connect(retranslate)   # 切换语言时刷新
"""
import json
import logging
from pathlib import Path

from shadowtalk.config.settings import Settings
from shadowtalk.config.paths import resource_path

logger = logging.getLogger(__name__)

# {lang_code: {source_str: translated_str}}
_translations: dict[str, dict[str, str]] = {}
_lang = "zh"
# 语言切换时的回调列表（各 UI 组件注册自己的刷新函数）
_listeners: list = []

# 支持的语言（显示名用于下拉框）
LANGUAGES = {
    "zh": "中文",
    "en": "English",
}


def load() -> None:
    """加载全部翻译文件并恢复上次选择的语言（启动时调用一次）。"""
    global _lang, _translations, _listeners
    _listeners = []
    _translations = {}
    for lang in LANGUAGES:
        p = resource_path(f"resources/lang/{lang}.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        except FileNotFoundError:
            logger.warning("翻译文件缺失：%s", p)
            _translations[lang] = {}
        except json.JSONDecodeError as e:
            logger.error("翻译文件 JSON 解析失败 %s：%s", p, e)
            _translations[lang] = {}
    _lang = Settings.get("language") or "zh"
    if _lang not in LANGUAGES:
        _lang = "zh"


def tr(source: str) -> str:
    """返回 source 在当前语言的译文（无译文则回退到 source 自身）。"""
    return _translations.get(_lang, {}).get(source, source)


def set_language(lang: str) -> None:
    """切换语言并通知所有监听者刷新。"""
    global _lang
    if lang not in LANGUAGES or lang == _lang:
        return
    _lang = lang
    Settings.set("language", lang)
    for fn in _listeners:
        try:
            fn()
        except Exception as e:
            logger.error("语言切换回调失败：%s", e, exc_info=True)


def on_language_changed(fn) -> None:
    """注册语言切换回调（fn 无参数）。"""
    _listeners.append(fn)


def language() -> str:
    """返回当前语言代码（"zh" / "en"）。"""
    return _lang
