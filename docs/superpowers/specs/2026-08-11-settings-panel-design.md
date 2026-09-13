# ShadowTalk 影聊 — 设置面板设计规格

> 日期：2026-08-11
> 版本：V1.0 第四轮
> 状态：待审核
> 范围：设置面板（API配置、记忆参数、数据操作）

---

## 1. 概述

本轮设计覆盖 ShadowTalk 的设置面板，包括：
- OpenAI 兼容接口配置（API地址、Key、模型等）
- 记忆引擎参数自定义（raw_keep_max、summary_batch_size 等）
- 手动数据操作（扫描过期摘要、清空聊天记录）

### 1.1 设计原则

- **独立对话框**：以 QDialog 形式弹出，不干扰聊天主界面
- **标签页分组**：API 配置 / 记忆参数 / 数据操作，清晰分区
- **即时保存**：点击保存后立即写入数据库并生效
- **取消不保存**：取消修改直接关闭，不影响当前配置

---

## 2. 面板布局

```
┌─────────────────────────────────────────┐
│  设置                             [X]   │
├───────────────┬─────────────────────────┤
│  API 配置     │                         │
│  记忆参数     │  [当前选中标签页内容]    │
│  数据操作     │                         │
├───────────────┴─────────────────────────┤
│                        [取消] [保存]    │
└─────────────────────────────────────────┘
```

### 文件结构

```
ui/widgets/
└── settings_dialog.py    # 设置对话框（含三个标签页）
```

---

## 3. 标签页 1：API 配置

| 字段 | 控件 | 默认值 | 说明 |
|---|---|---|---|
| API 地址 | QLineEdit | https://api.openai.com/v1 | 支持 DeepSeek 等兼容接口 |
| API Key | QLineEdit (Password) | （空） | 显示为 •••• |
| 模型名称 | QLineEdit | gpt-4o-mini | 如 deepseek-chat |
| Temperature | QSlider + QLabel | 0.7 | 范围 0.0 ~ 2.0，步进 0.01 |
| 最大输出长度 | QSpinBox | 2000 | 范围 100 ~ 32000 |

---

## 4. 标签页 2：记忆参数

| 字段 | 控件 | 默认值 | 范围 |
|---|---|---|---|
| raw_keep_max | QSpinBox | 50 | 10 ~ 200 |
| summary_batch_size | QSpinBox | 30 | 10 ~ 100 |
| summary_valid_days | QSpinBox | 30 | 7 ~ 365 |
| 摘要字数限制 | QSpinBox | 50 | 20 ~ 200 |
| max_context_tokens | QSpinBox | 8000 | 1000 ~ 32000 |
| L2 上限 | QSpinBox | 5 | 1 ~ 20 |

每个参数旁边显示一行灰色提示说明，如："未归档对话中优先保留原文的最大阈值（轮）"。

---

## 5. 标签页 3：数据操作

```
┌─────────────────────────────────────────┐
│  数据操作                               │
│                                         │
│  [手动扫描过期摘要]                      │
│  立即扫描并合并所有好友的过期批次摘要     │
│                                         │
│  [清空当前好友聊天记录]                   │
│  清空与 小明 的全部聊天记录              │
│  保留人设 Prompt                        │
│                                         │
└─────────────────────────────────────────┘
```

### 5.1 手动扫描过期摘要

```python
def _on_scan_now(self):
    """立即执行一次过期摘要扫描合并"""
    BackgroundScanner().scan_now()
    QMessageBox.information(self, "完成", "扫描完成")
```

### 5.2 清空当前好友聊天记录

```python
def _on_clear_chat(self):
    """清空当前好友的 L0/L1/L2，保留 L3 人设"""
    reply = QMessageBox.warning(
        self, "确认清空",
        f"确定清空与 {friend_name} 的全部聊天记录？\n"
        f"（人设 Prompt 将保留）",
        QMessageBox.Yes | QMessageBox.No
    )
    if reply == QMessageBox.Yes:
        MessageRepository.clear_by_friend(self.current_friend_id)
        BatchSummaryRepository.clear_by_friend(self.current_friend_id)
        HighLevelSummaryRepository.clear_by_friend(self.current_friend_id)
        QMessageBox.information(self, "完成", "聊天记录已清空")
```

---

## 6. 保存逻辑

```python
def _on_save(self):
    """保存所有设置"""
    # API 配置
    Settings.set("api_base_url", self.api_url_input.text())
    Settings.set("api_key", self.api_key_input.text())
    Settings.set("model_name", self.model_input.text())
    Settings.set("temperature", str(self.temperature_slider.value() / 100))
    Settings.set("max_output_tokens", str(self.max_output_spinbox.value()))
    
    # 记忆参数
    Settings.set("raw_keep_max", str(self.raw_keep_spinbox.value()))
    Settings.set("summary_batch_size", str(self.batch_spinbox.value()))
    Settings.set("summary_valid_days", str(self.valid_days_spinbox.value()))
    Settings.set("daily_summary_word_limit", str(self.word_limit_spinbox.value()))
    Settings.set("max_context_tokens", str(self.max_tokens_spinbox.value()))
    Settings.set("l2_limit", str(self.l2_limit_spinbox.value()))
    
    self.accept()
```

---

## 7. 边界处理

| 场景 | 处理 |
|---|---|
| API Key 为空时保存 | 提示但不阻止（用户可能还没配 API） |
| 取消修改 | 不保存，直接关闭对话框 |
| 参数超出范围 | SpinBox 自带范围限制 |
| 手动扫描时正在打包 | 写锁保证串行，不会冲突 |
| 清空聊天时当前无好友选中 | 按钮禁用或提示请先选择好友 |

---

## 8. 四轮设计总结

| 轮次 | 模块 | 文档 |
|---|---|---|
| 第 1 轮 | 核心记忆引擎 | `2026-08-11-memory-engine-design.md` |
| 第 2 轮 | 数据层 + 好友管理 | `2026-08-11-data-layer-friend-management-design.md` |
| 第 3 轮 | 聊天界面 | `2026-08-11-chat-interface-design.md` |
| 第 4 轮 | 设置面板 | `2026-08-11-settings-panel-design.md` |

**全部设计完成，下一步：进入实现阶段。**
