# shadowtalk/config/settings.py
import json

from shadowtalk.data.database import Database


# 默认 API 配置（第一套：仅占位模板，用户需填入自己的 Key。
# 发布版不内置任何账号密钥，避免泄露）
_DEFAULT_API_CONFIG = {
    "name": "LongCat",
    "base_url": "https://api.longcat.chat/openai/v1",
    "api_key": "",
    "model_name": "LongCat-2.0",
    "temperature": "0.7",
    "max_output_tokens": "20000",
    "max_tool_calls": "15",
    "tool_timeout": "120",
}


class Settings:
    _cache = {}

    DEFAULTS = {
        "raw_keep_max": "50",
        "summary_batch_size": "30",
        "summary_valid_days": "30",
        "summary_target_chars": "200",   # L1 摘要目标字数（软目标，超出保留全文不截断）
        "max_context_tokens": "8000",
        "l2_limit": "5",
        # 当前激活的 API 配置（flat keys，供 AIClient 直接读取）
        "api_base_url": _DEFAULT_API_CONFIG["base_url"],
        "api_key": _DEFAULT_API_CONFIG["api_key"],
        "model_name": _DEFAULT_API_CONFIG["model_name"],
        "temperature": _DEFAULT_API_CONFIG["temperature"],
        "max_output_tokens": _DEFAULT_API_CONFIG["max_output_tokens"],
        "max_tool_calls": _DEFAULT_API_CONFIG["max_tool_calls"],
        "tool_timeout": _DEFAULT_API_CONFIG["tool_timeout"],
        # 多套 API 配置（JSON 数组）+ 激活索引
        "api_configs": json.dumps([_DEFAULT_API_CONFIG]),
        "active_api_index": "0",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
        "tts_auto_play": "1",
        "theme": "light",
        "language": "zh",   # 界面语言：zh（中文）/ en（英文）
        # V1.4-Add 邮件配置（全局单份，本地用户自己用来收发信）
        "mail_smtp_host": "",
        "mail_smtp_port": "587",
        "mail_smtp_use_tls": "1",
        "mail_smtp_user": "",
        "mail_smtp_password": "",
        "mail_imap_host": "",
        "mail_imap_port": "993",
        "mail_imap_user": "",
        "mail_imap_password": "",
        "mail_poll_interval_seconds": "180",   # 生产最小 3 分钟（防风控）
        "mail_dev_mode": "0",                   # 1=MailHog 测试（无 SSL，轮询 30s）
    }

    @classmethod
    def get(cls, key: str) -> str:
        if key not in cls._cache:
            conn = Database.get_connection()
            row = conn.execute(
                "SELECT value FROM app_config WHERE key=?", (key,)
            ).fetchone()
            cls._cache[key] = row["value"] if row else cls.DEFAULTS.get(key, "")
        return cls._cache[key]

    @classmethod
    def set(cls, key: str, value: str):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value, update_time) "
                "VALUES (?, ?, datetime('now'))",
                (key, value)
            )
        cls._cache[key] = value

    @classmethod
    def get_int(cls, key: str) -> int:
        return int(cls.get(key))

    @classmethod
    def get_float(cls, key: str) -> float:
        return float(cls.get(key))

    @classmethod
    def get_bool(cls, key: str) -> bool:
        return cls.get(key) == "1"

    @classmethod
    def init_defaults(cls):
        conn = Database.get_connection()
        for key, value in cls.DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
                (key, value)
            )
        conn.commit()
        cls._cache.clear()

    # ── 多套 API 配置管理 ─────────────────────────────────────────

    @classmethod
    def get_api_configs(cls) -> list[dict]:
        """读取 API 配置列表（JSON 解析失败时回落到内置默认单份）。"""
        raw = cls.get("api_configs")
        try:
            configs = json.loads(raw)
            if isinstance(configs, list) and configs:
                return configs
        except (json.JSONDecodeError, TypeError):
            pass
        return [_DEFAULT_API_CONFIG.copy()]

    @classmethod
    def save_api_configs(cls, configs: list[dict]) -> None:
        """保存 API 配置列表（JSON 序列化）。"""
        cls.set("api_configs", json.dumps(configs, ensure_ascii=False))

    @classmethod
    def get_active_api_index(cls) -> int:
        """读取激活配置索引（越界回落 0）。"""
        idx = cls.get_int("active_api_index")
        configs = cls.get_api_configs()
        return idx if 0 <= idx < len(configs) else 0

    @classmethod
    def set_active_api_index(cls, index: int) -> None:
        """设置激活配置索引，并把该配置同步写入 flat keys（供 AIClient 读取）。"""
        configs = cls.get_api_configs()
        if not (0 <= index < len(configs)):
            return
        cfg = configs[index]
        cls.set("active_api_index", str(index))
        cls.set("api_base_url", cfg.get("base_url", ""))
        cls.set("api_key", cfg.get("api_key", ""))
        cls.set("model_name", cfg.get("model_name", ""))
        cls.set("temperature", str(cfg.get("temperature", "0.7")))
        cls.set("max_output_tokens", str(cfg.get("max_output_tokens", "20000")))
        cls.set("max_tool_calls", str(cfg.get("max_tool_calls", "15")))
        cls.set("tool_timeout", str(cfg.get("tool_timeout", "120")))

    @classmethod
    def get_active_api_config(cls) -> dict:
        """读取当前激活的 API 配置。"""
        configs = cls.get_api_configs()
        idx = cls.get_active_api_index()
        return configs[idx] if configs else _DEFAULT_API_CONFIG.copy()
