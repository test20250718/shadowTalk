from shadowtalk.config.settings import Settings


def test_get_default_value():
    Settings.init_defaults()
    assert Settings.get("raw_keep_max") == "50"
    assert Settings.get("summary_batch_size") == "30"


def test_set_and_get():
    Settings.set("test_param", "hello")
    assert Settings.get("test_param") == "hello"


def test_get_int():
    Settings.set("int_param", "42")
    assert Settings.get_int("int_param") == 42


def test_get_float():
    Settings.set("float_param", "3.14")
    assert abs(Settings.get_float("float_param") - 3.14) < 0.001


def test_missing_key_returns_empty():
    assert Settings.get("nonexistent_key_zzz") == ""


def test_tts_defaults():
    Settings.init_defaults()
    assert Settings.get("tts_voice") == "zh-CN-XiaoxiaoNeural"
    assert Settings.get("tts_auto_play") == "1"


def test_theme_default():
    Settings.init_defaults()
    assert Settings.get("theme") == "light"


def test_tool_work_defaults():
    """AI 干活相关默认：工具调用上限 15 次（曾 5 次易触发"掉线"）、
    单次工具执行超时 120 秒（曾 30 秒不够干慢活）"""
    Settings.init_defaults()
    assert Settings.get("max_tool_calls") == "15"
    assert Settings.get("tool_timeout") == "120"
