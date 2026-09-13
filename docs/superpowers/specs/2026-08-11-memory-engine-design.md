# ShadowTalk 影聊 — 核心记忆引擎设计规格

> 日期：2026-08-11
> 版本：V1.0 第一轮
> 状态：待审核
> 范围：核心记忆引擎（四层分级记忆 L0-L3）

---

## 1. 概述

记忆引擎是 ShadowTalk 的核心模块，负责自动管理 AI 对话上下文长度、节约 Token、让记忆逻辑贴近人类习惯。采用**条数优先、时间兜底**的双触发策略，实现四层分级记忆架构。

### 1.1 设计原则

- **纯函数式**：记忆引擎只负责"组装上下文"，不调用 AI、不处理 UI
- **管道模式**：每层独立提取，便于单独测试和维护
- **数据库原文永久保存**：裁剪只影响本次发送的上下文，不删除历史
- **零额外依赖**：Token 计数用字符估算，不引入 tiktoken

### 1.2 四层记忆定义

| 层级 | 名称 | 内容 | 有效期 | 可裁剪 |
|---|---|---|---|---|
| L3 | 永久固定记忆 | 好友人设 Prompt | 永久 | 否 |
| L2 | 高阶聚合摘要 | 多条过期批次摘要合并 | 永久 | 否 |
| L1 | 批次摘要池 | 30轮打包生成的简短摘要 | 30天 | 否 |
| L0 | 未归档原始对话 | 完整原始对话记录 | 未归档 | **是** |

上下文拼接固定顺序：`L3 → L2 → L1 → L0 → 用户最新消息`

---

## 2. 文件结构

```
shadowtalk/
├── core/
│   ├── __init__.py
│   ├── memory_engine.py      # 主管道：build_context()
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── l3_persona.py     # L3 永久人设提取
│   │   ├── l2_summary.py     # L2 高阶聚合摘要提取
│   │   ├── l1_summary.py     # L1 批次摘要提取
│   │   └── l0_raw.py         # L0 未归档原文提取
│   ├── archiver.py           # 归档检查 & 打包触发
│   ├── summarizer.py         # 调用AI生成摘要（含重试、截断兜底）
│   ├── token_budget.py       # Token估算 & 裁剪策略
│   └── background_scanner.py # QTimer 定时扫描过期摘要
├── data/
│   ├── __init__.py
│   ├── database.py           # SQLite 连接管理
│   └── repositories.py       # 各表 CRUD 操作
├── models/
│   ├── __init__.py
│   └── entities.py           # 数据类
└── config/
    ├── __init__.py
    └── settings.py           # 全局参数管理
```

---

## 3. 主管道算法

### 3.1 入口函数

```python
def build_context(friend_id: int, user_message: str) -> list[dict]:
    """
    组装完整的 AI 上下文消息列表。
    返回: [{"role": "system"|"user"|"assistant", "content": str, "layer": "L0"|"L1"|"L2"|"L3"}, ...]
    """
```

### 3.2 执行流程

```
输入: friend_id + user_message
  ↓
[1] archiver.check_and_archive(friend_id)     ← 归档检查（可能触发打包）
  ↓
[2] l3.extract(friend_id)                     ← L3 永久人设
[3] l2.extract(friend_id)                     ← L2 高阶聚合摘要
[4] l1.extract(friend_id)                     ← L1 有效期内批次摘要
[5] l0.extract(friend_id)                     ← L0 未归档原文
  ↓
[6] token_budget.trim(context, max_tokens)    ← Token 预算检查 & 裁剪 L0
  ↓
[7] 追加用户最新消息 {"role": "user", "content": user_message}
  ↓
输出: 组装好的 messages 列表
```

### 3.3 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 归档检查在最前面 | ✅ | 确保上下文干净 |
| 裁剪只针对 L0 | ✅ | L3/L2/L1 是精华记忆，不能动 |
| 裁剪后不写回数据库 | ✅ | 原文永久保存 |
| 返回带 layer 标记的消息 | ✅ | 裁剪时区分层级 |
| 返回标准 OpenAI 格式 | ✅ | 聊天模块零改动转发 |

---

## 4. 归档器 (archiver.py)

### 4.1 条数触发打包

```python
def check_and_archive(friend_id: int):
    """每次构建上下文前调用"""
    raw_count = repo.count_unarchived_rounds(friend_id)
    
    if raw_count <= raw_keep_max:       # 默认 50
        return                          # 不触发任何摘要逻辑
    
    overflow = raw_count - raw_keep_max
    buffer = repo.get_oldest_unarchived(friend_id, overflow)
    
    if len(buffer) < summary_batch_size:  # 默认 30
        return                          # 不足30轮，禁止生成摘要
    
    to_archive = buffer[:summary_batch_size]
    summarizer.generate_batch_summary(friend_id, to_archive)
```

### 4.2 打包规则

- 未归档总轮数 ≤ raw_keep_max → 全部原文送入，不生成摘要
- 未归档总轮数 ＞ raw_keep_max → 最新 raw_keep_max 条保留原文，更早的进入缓冲区
- 缓冲区 ＜ summary_batch_size → 不生成摘要
- 缓冲区 ≥ summary_batch_size → 截取最前面 30 轮生成摘要，标记为已归档

---

## 5. 摘要生成器 (summarizer.py)

### 5.1 批次摘要生成 (L1)

```python
def generate_batch_summary(friend_id: int, messages: list) -> str:
    """生成一条批次摘要，带重试和截断兜底"""
    prompt = build_summary_prompt(messages)
    
    for attempt in range(2):              # 最多2次尝试
        text = ai_client.chat(prompt)
        if len(text) <= daily_summary_word_limit:   # 默认 50 字
            break
        # 超长 → 重试一次
    else:
        text = text[:daily_summary_word_limit] + "…[摘要截断]"
    
    with db_transaction():
        repo.save_batch_summary(friend_id, text, start_round, end_round)
        repo.mark_messages_archived([m.id for m in messages])
```

### 5.2 高阶聚合摘要生成 (L2)

```python
def generate_high_level_summary(expired_summaries: list) -> str:
    """将多条过期批次摘要合并为一条 L2 高阶聚合摘要"""
    prompt = build_merge_prompt(expired_summaries)
    text = ai_client.chat(prompt)
    return text
```

### 5.3 容错策略

| 场景 | 处理 |
|---|---|
| AI 调用失败（网络/报错） | 捕获异常，记录日志，本轮不打包 |
| 摘要超长 | 重试一次 → 仍超长 → 强制截断 + 标记 `[摘要截断]` |
| 摘要为空 | 跳过，不写入，记录警告 |
| 并发写入 | `threading.Lock` 串行化写操作 |

---

## 6. 后台扫描器 (background_scanner.py)

### 6.1 时间兜底合并

```python
class BackgroundScanner:
    """QTimer 驱动，每小时检查一次过期摘要"""
    
    def __init__(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(3600 * 1000)       # 每小时
    
    def scan(self):
        for friend_id in repo.get_all_friend_ids():
            expired = repo.get_expired_summaries(friend_id, summary_valid_days)
            if not expired:
                continue
            
            l2_text = summarizer.generate_high_level_summary(expired)
            
            with db_transaction():
                repo.save_high_level_summary(friend_id, l2_text)
                repo.mark_summaries_archived([s.id for s in expired])
            
            self._enforce_l2_limit(friend_id)
```

### 6.2 L2 数量上限

```python
def _enforce_l2_limit(self, friend_id: int, limit: int = 5):
    """单好友 L2 超过 limit 条时，合并最旧的几条为 1 条"""
    l2_list = repo.get_all_high_level_summaries(friend_id)
    if len(l2_list) <= limit:
        return
    to_merge = l2_list[:len(l2_list) - limit + 1]
    merged = summarizer.merge_high_level_summaries(to_merge)
    with db_transaction():
        repo.save_high_level_summary(friend_id, merged)
        repo.mark_summaries_archived([s.id for s in to_merge])
```

---

## 7. Token 预算 (token_budget.py)

### 7.1 估算策略

```python
def estimate_tokens(text: str) -> int:
    """字符数估算：总字符数 // 2（偏保守）"""
    return len(text) // 2
```

选择字符估算而非 tiktoken 的理由：
- 零额外依赖
- PySide6 纯文本场景下足够准确
- 保守估算（多估）比低估安全，避免 API 报错

### 7.2 裁剪策略

```python
def trim_context(messages: list[dict], max_tokens: int) -> list[dict]:
    """从 L0 最旧消息开始裁剪，直到满足预算"""
    total = sum(estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages
    
    protected = [m for m in messages if m.get("layer") != "L0"]
    l0_msgs = [m for m in messages if m.get("layer") == "L0"]
    
    while l0_msgs and total > max_tokens:
        removed = l0_msgs.pop(0)             # 移除最旧
        total -= estimate_tokens(removed["content"])
    
    return protected + l0_msgs
```

**注意**：L0 全部移除后仍超限 → 不再移除 L1/L2/L3，直接返回，由 API 报错。

---

## 8. 错误处理

| 错误类型 | 处理方式 | 用户感知 |
|---|---|---|
| AI 调用超时/网络错误 | 捕获异常，记录日志，返回空摘要 | 无感知 |
| AI 返回空字符串 | 视为失败，不写入 | 无感知 |
| 摘要超长截断 | 写入截断标记 | 无感知（排查可见） |
| Token 裁剪后仍超限 | 不裁剪 L1/L2/L3 | API 报错时聊天模块提示 |
| 数据库写入失败 | 事务回滚，记录日志 | 无感知 |
| 并发写冲突 | `threading.Lock` 串行化 | 无感知 |

---

## 9. 边界场景

| 场景 | 预期行为 |
|---|---|
| 好友没有任何对话记录 | 只发送 L3 人设 + 用户消息 |
| 好友只有 L3 人设，无摘要 | 跳过 L2/L1/L0 |
| 所有 L0 都被裁剪完仍超限 | 返回 protected 部分，让 API 决定 |
| 软件崩溃时正在生成摘要 | 事务未提交 → 回滚，原文保持未归档 |
| 用户手动清空聊天记录 | 删除所有 L0/L1/L2，保留 L3 人设 |
| 单条消息本身就超过 max_tokens | 不裁剪单条，由 API 报错 |

---

## 10. 日志策略

```python
import logging
logger = logging.getLogger("shadowtalk.memory")

logger.info(f"好友 {friend_id}: 打包 {len(messages)} 轮 → 摘要 {summary_id}")
logger.warning(f"好友 {friend_id}: 摘要超长 ({len(text)}字)，已截断")
logger.error(f"好友 {friend_id}: AI 调用失败 {exc}")
```

日志输出到 `logs/shadowtalk.log`，不弹窗打扰用户。

---

## 11. 全局参数（默认值）

| 参数名 | 默认值 | 说明 |
|---|---|---|
| raw_keep_max | 50 轮 | 未归档对话中优先保留原文的最大阈值 |
| summary_batch_size | 30 轮 | 生成一条批次摘要所需的最小对话轮数 |
| summary_valid_days | 30 天 | 批次摘要的有效期 |
| daily_summary_word_limit | 50 字 | 单条批次摘要字数限制 |
| max_context_tokens | 根据模型动态设置 | 上下文总 Token 上限 |
| l2_limit | 5 条 | 单好友 L2 高阶摘要数量上限 |

---

## 12. 待后续轮次覆盖

本轮**不涉及**以下内容，留待后续轮次设计：

- 数据库表结构详细定义（第二轮：数据层）
- 好友管理模块接口（第二轮：好友管理）
- 聊天界面如何调用记忆引擎（第三轮：聊天界面）
- 设置面板如何修改全局参数（第四轮：设置面板）
- AI 客户端封装（openai 兼容接口 SDK 集成）

---

## 13. 极端场景校验（已验证）

1. **每天只聊1条，连续40天**：总轮数 40 ＜ 50，全程发送原文，不压缩
2. **单日密集聊天90轮**：溢出缓冲区 40 轮，取出最早 30 轮生成摘要，剩余 10 轮留在未归档池
3. **多条批次摘要超过30天**：后台自动合并为一条 L2 高阶摘要
4. **L2 超过 5 条**：自动合并最旧的几条为 1 条
