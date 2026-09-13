# tests/test_token_budget.py
import pytest
from shadowtalk.core.token_budget import estimate_tokens, trim_context


def test_estimate_tokens_chinese():
    assert estimate_tokens("你好" * 50) == 50

def test_estimate_tokens_english():
    assert estimate_tokens("a" * 100) == 50

def test_trim_context_no_trim_needed():
    messages = [
        {"role": "system", "content": "hi", "layer": "L3"},
        {"role": "user", "content": "hello", "layer": "L0"},
    ]
    result = trim_context(messages, 1000)
    assert len(result) == 2

def test_trim_context_trims_l0_oldest_first():
    messages = [
        {"role": "system", "content": "persona", "layer": "L3"},
        {"role": "user", "content": "a" * 100, "layer": "L0"},
        {"role": "assistant", "content": "b" * 100, "layer": "L0"},
        {"role": "user", "content": "c" * 100, "layer": "L0"},
    ]
    result = trim_context(messages, 75)
    assert result[0]["layer"] == "L3"
    contents = [m["content"] for m in result]
    assert "a" * 100 not in contents

def test_trim_context_never_trims_non_l0():
    messages = [
        {"role": "system", "content": "x" * 1000, "layer": "L3"},
        {"role": "user", "content": "y" * 1000, "layer": "L0"},
    ]
    result = trim_context(messages, 100)
    assert len(result) == 1
    assert result[0]["layer"] == "L3"
