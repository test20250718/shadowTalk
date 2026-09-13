# 人物级工作目录（Friend Workdir）设计

**Goal:** 把 AI 秘书的工作目录从全局设置移到每个好友（人物）的属性里，并在系统提示（L3）中注入该目录，让 AI 自动使用人物配置的目录读写文件——用户无需在人物提示词里额外写目录。

**背景:** 现有 `work_dir` 是全局设置（Settings + 设置对话框 + 启动创建目录）。用户实测「AI 写小说到指定目录」可用，但希望目录随人物走（不同人物写不同的书），且自动注入上下文。

## 决策（已与用户确认）

1. **彻底移除全局 work_dir 设置**：设置对话框的行、Settings DEFAULTS 项、main.py 启动创建目录全部删除
2. **好友未配置目录时拒绝并提示**：AI 请求执行代码/写文件时拒绝，返回「当前好友未配置工作目录」；纯聊天不受影响

## 架构

采用方案 A：`friends` 表加列 + L3 系统提示注入。与现有 `ai_role`/`user_role` 机制完全同构。

### 1. 数据层

- `friends` 表新增列 `work_dir TEXT DEFAULT ''`
- 迁移：照抄 `database.py` 的 `ai_role` 模式——启动时检查 `PRAGMA table_info(friends)`，列不存在则 `ALTER TABLE friends ADD COLUMN work_dir TEXT DEFAULT ''`
- `FriendRepository.create/update` 的 allowed 字段集合加 `work_dir`，SQL 同步
- `FriendService.create` 透传 `work_dir` 参数（默认 `""`）

### 2. UI 层

- `FriendDialog`：在「AI 的角色」/「我的角色」下方新增一行「工作目录：」
  - `QLineEdit`（全路径）+「浏览…」按钮（`QFileDialog.getExistingDirectory`，选中后填全路径）
  - placeholder：`AI 可在此目录读写文件（留空则禁用文件操作）`
  - `get_data()` 返回 `work_dir`；`_fill_data()` 回填
- 删除：
  - `settings_dialog.py` 的工作目录行（含 `_browse_work_dir`）
  - `settings.py` DEFAULTS 的 `"work_dir"`
  - `main.py` 的 `os.makedirs(Settings.get("work_dir"), ...)`

### 3. 上下文注入（l3_persona.py）

在 `extract()` 组装 parts 时，若 `friend["work_dir"]` 非空，追加：

```
你的工作目录是 <path>。需要读写文件、生成文档时，请使用该目录；目录内可自由读写。
```

为空则完全不注入（模型不知道存在文件工具）。

### 4. AIWorker 行为

- `MainWindow._on_message_sent`：创建 worker 时从 `FriendRepository.get_by_id(current_friend_id)["work_dir"]` 取目录传入（不再读 Settings；不再 `or "shadowtalk/workdir/"` 回退）
- `AIWorker._run_tool`：`work_dir` 为空时，**拒绝一切代码执行**（不再 fallback 到 `"."`），返回：
  `当前好友未配置工作目录。请在好友设置中添加工作目录，即可让我读写文件。`
  - 有目录时行为不变：目录内自由读写，目录外需审批卡片

### 5. 测试

- 删除 `tests/test_settings.py` 的 `test_work_dir_default` / `test_work_dir_set_and_get`
- 新增：
  - `tests/test_repositories.py`（或对应文件）：friend create 带 `work_dir`、update 改 `work_dir`、get 读回
  - `tests/test_l3_persona.py`：有目录 → 系统提示含目录路径；无目录 → 不注入任何目录内容
- 冒烟：空目录时 AIWorker 拒绝执行（user_denied 风格提示），有目录时目录内写入正常

### 6. 兼容性

- 已有好友 `work_dir` 默认空 → 文件操作被拒并提示，需手动编辑好友填入路径
- 磁盘上旧 `shadowtalk/workdir/` 不删除；用户可把目录路径填到对应人物属性继续使用

## 边界情况

- 目录路径不存在：不自动创建（人物目录由用户选择真实存在的目录）；若用户手输不存在的路径，子进程 `cwd` 会报错，经 `ExecResult` 返回给模型（可接受，不做额外校验）
- 目录外写入审批逻辑不变（approval card 照旧）
- `chat_with_tools`、`python_executor` 不感知目录，无需改动
