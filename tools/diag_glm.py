#!/usr/bin/env python
"""诊断 GLM API 连接：尝试多个模型名，找出可用的。"""
import sqlite3
import json
import urllib.request
import urllib.error

conn = sqlite3.connect("shadowtalk.db")
cfg = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM app_config").fetchall()}
configs = json.loads(cfg.get("api_configs", "[]"))

# 找到 GLM 配置
for c in configs:
    if "glm" in c.get("model_name", "").lower() or "bigmodel" in c.get("base_url", "").lower():
        base_url = c["base_url"].rstrip("/") + "/chat/completions"
        api_key = c["api_key"]
        print(f"测试配置: {c.get('name')}  url={c['base_url']}")
        print(f"Key 前8位: {api_key[:8]}...")
        # 试几个模型名
        for model in ["glm-5.2", "glm-5", "glm-4-flash", "glm-4", "glm-4-plus", "glm-4-air"]:
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10,
            }).encode()
            req = urllib.request.Request(
                base_url, data=body,
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"  {model}: OK")
                    break
            except urllib.error.HTTPError as e:
                err = e.read().decode()[:120]
                print(f"  {model}: HTTP {e.code} - {err}")
            except Exception as e:
                print(f"  {model}: ERROR - {e}")
        print()
