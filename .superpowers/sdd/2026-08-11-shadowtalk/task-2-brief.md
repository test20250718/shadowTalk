# Task 2: Settings Management

**Files:**
- Create: `shadowtalk/config/__init__.py`
- Create: `shadowtalk/config/settings.py`
- Create: `tests/test_settings.py`

## Interfaces
- Consumes: `Database.get_connection()`, `Database.transaction()`
- Produces:
  - `Settings.get(key: str) -> str`
  - `Settings.set(key: str, value: str) -> None`
  - `Settings.get_int(key: str) -> int`
  - `Settings.get_float(key: str) -> float`
  - `Settings.init_defaults() -> None`

## Implementation

```python
# shadowtalk/config/settings.py
from shadowtalk.data.database import Database


class Settings:
    _cache = {}

    DEFAULTS = {
        "raw_keep_max": "50",
        "summary_batch_size": "30",
        "summary_valid_days": "30",
        "daily_summary_word_limit": "50",
        "max_context_tokens": "8000",
        "l2_limit": "5",
        "api_base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model_name": "gpt-4o-mini",
        "temperature": "0.7",
        "max_output_tokens": "2000",
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
    def init_defaults(cls):
        conn = Database.get_connection()
        for key, value in cls.DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
                (key, value)
            )
        conn.commit()
        cls._cache.clear()
```

## Tests

```python
# tests/test_settings.py
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
```

## TDD Steps
1. Write failing test
2. Run to verify FAIL
3. Implement Settings class
4. Run to verify PASS
5. Commit
