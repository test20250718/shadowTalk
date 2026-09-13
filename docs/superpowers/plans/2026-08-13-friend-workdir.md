# 人物级工作目录（Friend Workdir）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AI 秘书的工作目录从全局设置移到每个好友属性（`friends.work_dir`），并在 L3 系统提示中注入该目录，AI 自动使用人物目录读写文件。

**Architecture:** `friends` 表加 `work_dir` 列（复用 `ai_role` 迁移模式）→ `FriendDialog` 加输入行 → `l3_persona.extract()` 组装系统提示时注入 → `AIWorker` 从好友记录取目录、空目录拒绝执行 → 删除全部全局 work_dir 代码。

**Tech Stack:** PySide6、sqlite3、pytest（conftest.py 已为每个测试隔离临时 DB）。

## Global Constraints

- 彻底移除全局 work_dir：`settings_dialog.py` 行、`settings.py` DEFAULTS 项、`main.py` 启动创建目录，全部删除
- 好友未配置目录 → 拒绝一切代码执行，提示「当前好友未配置工作目录。请在好友设置中添加工作目录，即可让我读写文件。」
- 注入文案（与 spec 一致）：`你的工作目录是 <path>。需要读写文件、生成文档时，请使用该目录；目录内可自由读写。`
- 有目录时行为不变：目录内自由读写，目录外写需审批卡片
- 所有 UI 文案中文；新组件注释中文（项目惯例）
- 测试数据库由 `tests/conftest.py` 自动隔离，测试无需手动建库

---

### Task 1: 数据层 — friends.work_dir 列 + Repository/Service 透传

**Files:**
- Modify: `shadowtalk/data/database.py`（SCHEMA + `_migrate`）
- Modify: `shadowtalk/data/repositories.py`（`FriendRepository.insert` / `update`）
- Modify: `shadowtalk/core/friend_service.py`（`create` 透传）
- Test: `tests/test_repositories.py`（TestFriendRepository 追加）

**Interfaces:**
- Consumes: 无
- Produces:
  - `FriendRepository.insert(name, remark, system_prompt, avatar_path="", ai_role="", user_role="", work_dir="") -> int`
  - `FriendRepository.update(friend_id, **kwargs)` — allowed 集合含 `"work_dir"`
  - `FriendRepository.get_by_id(friend_id)` 返回行含 `work_dir` 键
  - `FriendService.create(name, remark, system_prompt, avatar_source_path="", ai_role="", user_role="", work_dir="") -> int`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_repositories.py` 的 `TestFriendRepository` 类末尾：

```python
    def test_insert_with_work_dir(self):
        fid = FriendRepository.insert("写手", "", "", work_dir="D:/novel/project1")
        friend = FriendRepository.get_by_id(fid)
        assert friend["work_dir"] == "D:/novel/project1"

    def test_update_work_dir(self):
        fid = FriendRepository.insert("写手", "", "")
        FriendRepository.update(fid, work_dir="E:/books")
        friend = FriendRepository.get_by_id(fid)
        assert friend["work_dir"] == "E:/books"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_repositories.py -v`
Expected: 2 个新测试 FAIL — `sqlite3.OperationalError: table friends has no column named work_dir`（`test_update_work_dir` 可能因 insert 签名不匹配而 `TypeError`，均符合预期）

- [ ] **Step 3: 实现数据层**

`shadowtalk/data/database.py` — SCHEMA 的 friends 表 `user_role` 行后加一列：

```python
    user_role TEXT DEFAULT '',
    work_dir TEXT DEFAULT '',
```

`_migrate` 方法追加（`user_role` 检查之后）：

```python
        if "work_dir" not in existing:
            conn.execute("ALTER TABLE friends ADD COLUMN work_dir TEXT DEFAULT ''")
```

`shadowtalk/data/repositories.py` — `FriendRepository.insert` 签名与 SQL：

```python
    @staticmethod
    def insert(name, remark, system_prompt, avatar_path="",
               ai_role="", user_role="", work_dir=""):
        with Database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO friends (name, remark, system_prompt, avatar_path, ai_role, user_role, work_dir) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, remark, system_prompt, avatar_path, ai_role, user_role, work_dir)
            )
            return cursor.lastrowid
```

`update` 的 allowed 集合加 `"work_dir"`：

```python
        allowed = {"name", "remark", "system_prompt", "avatar_path", "ai_role", "user_role", "work_dir"}
```

`shadowtalk/core/friend_service.py` — `create` 签名与 `FriendRepository.insert` 调用：

```python
    @staticmethod
    def create(name: str, remark: str, system_prompt: str,
               avatar_source_path: str = "",
               ai_role: str = "", user_role: str = "", work_dir: str = "") -> int:
```

```python
        friend_id = FriendRepository.insert(
            name, remark, system_prompt, avatar_path,
            ai_role=ai_role, user_role=user_role, work_dir=work_dir
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_repositories.py tests/test_friend_service.py -v`
Expected: 全部 PASS（旧 5 个 + 新 2 个；friend_service 测试不回归）

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/data/database.py shadowtalk/data/repositories.py shadowtalk/core/friend_service.py tests/test_repositories.py
git commit -m "feat(core): add work_dir field to friends table with migration"
```

---

### Task 2: L3 上下文注入

**Files:**
- Modify: `shadowtalk/core/layers/l3_persona.py`
- Test: `tests/test_layers.py`（TestLayers 追加）

**Interfaces:**
- Consumes: `FriendRepository.get_by_id(friend_id)["work_dir"]`（Task 1）
- Produces: `l3.extract(friend_id)` — 当 work_dir 非空时 system prompt 含注入句；为空时不含

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_layers.py` 的 `TestLayers` 类末尾：

```python
    def test_l3_injects_work_dir(self):
        fid = FriendRepository.insert("秘书", "", "", work_dir="D:/novel/project1")
        result = l3.extract(fid)
        assert len(result) == 1
        assert "D:/novel/project1" in result[0]["content"]
        assert "工作目录" in result[0]["content"]

    def test_l3_empty_work_dir_no_injection(self):
        fid = FriendRepository.insert("秘书", "", "")
        result = l3.extract(fid)
        assert "工作目录" not in result[0]["content"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_layers.py -v`
Expected: 2 个新测试 FAIL（L3 content 中无"工作目录"）

- [ ] **Step 3: 实现注入**

`shadowtalk/core/layers/l3_persona.py` — 在 `ai_role`/`user_role` 处理之后、`system_prompt` 之前插入：

```python
    work_dir = friend["work_dir"] if friend["work_dir"] else ""

    if work_dir:
        parts.append(
            f"你的工作目录是 {work_dir}。需要读写文件、生成文档时，请使用该目录；目录内可自由读写。"
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_layers.py -v`
Expected: 全部 PASS（旧 8 个 + 新 2 个）

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/core/layers/l3_persona.py tests/test_layers.py
git commit -m "feat: inject friend work_dir into L3 persona prompt"
```

---

### Task 3: FriendDialog 工作目录行 + MainWindow 传参

**Files:**
- Modify: `shadowtalk/ui/widgets/friend_dialog.py`
- Modify: `shadowtalk/ui/main_window.py`（`_on_add_friend` / `_on_edit_friend`）
- Test: Create `tests/test_friend_dialog.py`

**Interfaces:**
- Consumes: `FriendService.create(..., work_dir=...)`、`FriendRepository.update(friend_id, work_dir=...)`（Task 1）
- Produces: `FriendDialog.get_data()["work_dir"]`（字符串，可能为空）

- [ ] **Step 1: 写失败测试**

Create `tests/test_friend_dialog.py`：

```python
"""FriendDialog 工作目录字段测试"""
import sys
from PySide6.QtWidgets import QApplication
from shadowtalk.ui.widgets.friend_dialog import FriendDialog

app = QApplication.instance() or QApplication(sys.argv)


def test_work_dir_input_blank_for_new_friend():
    dialog = FriendDialog()
    assert dialog.work_dir_input.text() == ""
    assert dialog.get_data()["work_dir"] == ""


def test_work_dir_fills_from_friend_and_returns():
    friend = {"name": "秘书", "remark": "", "ai_role": "", "user_role": "",
              "system_prompt": "", "avatar_path": "", "work_dir": "D:/novel/p1"}
    dialog = FriendDialog(friend=friend)
    assert dialog.work_dir_input.text() == "D:/novel/p1"
    assert dialog.get_data()["work_dir"] == "D:/novel/p1"


def test_work_dir_browse_button_exists():
    dialog = FriendDialog()
    from PySide6.QtWidgets import QPushButton
    buttons = dialog.findChildren(QPushButton)
    assert any(b.text() == "浏览…" for b in buttons)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_friend_dialog.py -v`
Expected: 3 个 FAIL — `AttributeError: 'FriendDialog' object has no attribute 'work_dir_input'`

- [ ] **Step 3: 实现对话框字段**

`shadowtalk/ui/widgets/friend_dialog.py` — 在 `user_role_input` 的 addRow 之后插入（保持现有表单样式）：

```python
        self.work_dir_input = QLineEdit()
        self.work_dir_input.setPlaceholderText("AI 可在此目录读写文件（留空则禁用文件操作）")
        self.work_dir_input.setStyleSheet(_input_style())
        work_dir_row = QHBoxLayout()
        work_dir_row.addWidget(self.work_dir_input, 1)
        work_dir_btn = QPushButton("浏览…")
        work_dir_btn.setCursor(Qt.PointingHandCursor)
        work_dir_btn.setStyleSheet(_secondary_btn_style())
        work_dir_btn.clicked.connect(self._pick_work_dir)
        work_dir_row.addWidget(work_dir_btn)
        form.addRow("工作目录：", work_dir_row)
```

`_pick_avatar` 方法后追加：

```python
    def _pick_work_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self.work_dir_input.setText(path)
```

`_fill_data` 中 `user_role_input` 之后追加：

```python
        self.work_dir_input.setText(friend["work_dir"])
```

`get_data` 返回值加 `"work_dir"`：

```python
            "work_dir": self.work_dir_input.text().strip(),
```

- [ ] **Step 4: 实现 MainWindow 传参**

`shadowtalk/ui/main_window.py` — `_on_add_friend` 的 `FriendService.create` 调用加：

```python
                work_dir=data.get("work_dir", ""),
```

`_on_edit_friend` 的 `FriendRepository.update` 调用加：

```python
                work_dir=data.get("work_dir", ""),
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_friend_dialog.py tests/test_friend_service.py -v`
Expected: 全部 PASS（新 3 个 + friend_service 不回归）

- [ ] **Step 6: 提交**

```bash
git add shadowtalk/ui/widgets/friend_dialog.py shadowtalk/ui/main_window.py tests/test_friend_dialog.py
git commit -m "feat(ui): add work_dir field with browse button to friend dialog"
```

---

### Task 4: AIWorker 从好友读目录 + 空目录拒绝 + 移除全局设置

**Files:**
- Modify: `shadowtalk/ui/threads/ai_worker.py`（空目录拒绝）
- Modify: `shadowtalk/ui/main_window.py`（`_on_message_sent` 传好友目录）
- Modify: `shadowtalk/ui/widgets/settings_dialog.py`（删除工作目录行 + `_browse_work_dir`）
- Modify: `shadowtalk/config/settings.py`（DEFAULTS 删除 `work_dir`）
- Modify: `shadowtalk/main.py`（删除启动创建目录）
- Test: `tests/test_settings.py`（删除 2 个 work_dir 测试）；冒烟脚本（临时，跑完删除）

**Interfaces:**
- Consumes: `FriendRepository.get_by_id(friend_id)["work_dir"]`（Task 1）
- Produces: `AIWorker(..., work_dir=friend_work_dir, ...)` — work_dir 为空时 `_run_tool` 直接返回拒绝文案，不启动子进程

- [ ] **Step 1: 删除全局 work_dir 测试**

`tests/test_settings.py` — 删除 `test_work_dir_default` 和 `test_work_dir_set_and_get` 两个函数（Task 4 之前刚加的）。

- [ ] **Step 2: 实现空目录拒绝**

`shadowtalk/ui/threads/ai_worker.py` — `_run_tool` 开头插入（在 `workdir = self.work_dir or "."` 之前，且**删除**该 fallback 行）：

```python
    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码；未配置工作目录时拒绝，目录外写需经 UI 审批"""
        if not self.work_dir:
            # 未配置工作目录：拒绝执行，避免写入当前进程目录
            return ("当前好友未配置工作目录。请在好友设置中添加工作目录，"
                    "即可让我读写文件。")

        from shadowtalk.core.python_executor import (
            run_with_approval, scan_write_paths,
        )

        outside_paths = scan_write_paths(code, self.work_dir)
        # 目录内写入无需审批，直接执行
        if not outside_paths:
            return run_with_approval(
                code, self.work_dir,
                approver=lambda paths, r: True, reason=reason
            ).summary()

        # 有目录外写入：无 UI 可审批 → 拒绝
        if not self._approval_answered:
            return run_with_approval(
                code, self.work_dir,
                approver=lambda paths, r: False, reason=reason
            ).summary()

        from PySide6.QtCore import QEventLoop

        loop = QEventLoop()

        def on_answer(allowed: bool):
            loop.quit()
            self._approved = allowed

        self._approved = False
        self.approval_requested.emit(code, outside_paths, reason)  # 发到主线程
        self._approval_answered.connect(on_answer)
        loop.exec()  # 嵌套事件循环，等待用户点击
        self._approval_answered.disconnect(on_answer)
        return run_with_approval(
            code, self.work_dir,
            approver=lambda paths, r: self._approved,
            reason=reason
        ).summary()
```

（`workdir = self.work_dir or "."` 行已删除，后续 `run_with_approval` 直接用 `self.work_dir`。）

- [ ] **Step 3: MainWindow 传好友目录**

`shadowtalk/ui/main_window.py` — `_on_message_sent` 中 worker 创建处替换为：

```python
        friend = FriendRepository.get_by_id(self.current_friend_id)
        friend_work_dir = friend["work_dir"] if friend else ""
        self.ai_worker = AIWorker(
            self.current_friend_id, text,
            ai_client, self._pending_context or context,
            work_dir=friend_work_dir,
            approval_answered=self.approval_answered,
        )
```

（注意：上方已有 `friend = FriendRepository.get_by_id(...)` 用于 `_pending_friend_name`，若保留则复用；删除原来的 `work_dir=Settings.get("work_dir") or "shadowtalk/workdir/"`。）

- [ ] **Step 4: 移除全局设置**

`shadowtalk/ui/widgets/settings_dialog.py`：
- 删除 `self.work_dir_input`、`browse_btn`、`work_row` 及 `api_layout.addRow("工作目录：", work_row)`（Task 4 之前刚加的）
- 删除 `_load_settings` 中 `self.work_dir_input.setText(...)`
- 删除 `_on_save` 中 `Settings.set("work_dir", ...)`
- 删除 `_browse_work_dir` 方法

`shadowtalk/config/settings.py` — DEFAULTS 删除：

```python
        "work_dir": "shadowtalk/workdir/",
```

`shadowtalk/main.py` — 删除：

```python
    os.makedirs(Settings.get("work_dir"), exist_ok=True)
```

- [ ] **Step 5: 验证**

Run: `pytest tests/test_settings.py tests/test_ai_client.py -v`
Expected: 全部 PASS（settings 5 个、ai_client 5 个）

Run: `grep -rn "work_dir" shadowtalk/ | grep -v __pycache__`
Expected: 仅剩 `shadowtalk/ui/threads/ai_worker.py`（参数/逻辑）、`shadowtalk/ui/main_window.py`（friend_work_dir）、`shadowtalk/ui/widgets/friend_dialog.py`、`shadowtalk/data/`（表结构/迁移）、`shadowtalk/core/layers/l3_persona.py`、`shadowtalk/core/friend_service.py`；**无** settings.py / settings_dialog.py / main.py 残留

- [ ] **Step 6: 冒烟验证**

Create `smoke_friend_workdir.py`（临时，验证后删除）：

```python
# 冒烟：空目录拒绝 + 有目录正常写入
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QObject, Signal, QCoreApplication, QEventLoop, QTimer

from shadowtalk.ui.threads.ai_worker import AIWorker


class Bridge(QObject):
    answered = Signal(bool)


class FakeClient:
    def __init__(self, code):
        self._code = code

    def chat_with_tools(self, messages, tool_runner):
        return tool_runner(self._code, "写一份报告")


def run(code, work_dir):
    app = QCoreApplication.instance() or QCoreApplication([])
    bridge = Bridge()
    client = FakeClient(code)
    worker = AIWorker(1, "test", client,
                      [{"role": "user", "content": "hi"}],
                      work_dir=work_dir,
                      approval_answered=bridge.answered)
    result = {}
    worker.approval_requested.connect(
        lambda c, paths, r: bridge.answered.emit(True))
    worker.finished.connect(lambda reply: result.setdefault("reply", reply))
    worker.failed.connect(lambda err: result.setdefault("error", err))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.failed.connect(loop.quit)
    QTimer.singleShot(8000, loop.quit)
    worker.start()
    loop.exec()
    worker.wait(3000)
    result.setdefault("reply", "<超时>")
    return result


if __name__ == "__main__":
    # 场景1：未配置目录 → 拒绝，不执行
    r1 = run("print('x')", "")
    assert "未配置工作目录" in r1["reply"], r1
    print(f"[1] 空目录拒绝: {r1['reply'][:40]!r}")

    # 场景2：有目录 → 目录内写入成功
    workdir = tempfile.mkdtemp(prefix="st_fw_")
    target = Path(workdir) / "out.txt"
    code = f"open({str(target)!r}, 'w').write('hi')"
    r2 = run(code, workdir)
    assert "退出码: 0" in r2["reply"], r2
    assert target.exists(), r2
    print(f"[2] 目录内写入: {r2['reply'][:40]!r}")

    print("SMOKE OK")
```

Run: `timeout 60 python -X utf8 smoke_friend_workdir.py`
Expected: `SMOKE OK`（两场景全过）

Run 后删除：`rm smoke_friend_workdir.py`

- [ ] **Step 7: 提交**

```bash
git add shadowtalk/ui/threads/ai_worker.py shadowtalk/ui/main_window.py shadowtalk/ui/widgets/settings_dialog.py shadowtalk/config/settings.py shadowtalk/main.py tests/test_settings.py
git commit -m "feat: per-friend work_dir with deny-when-unset; remove global work_dir"
```

---

### Task 5: 回归验证与收尾

**Files:**
- Test: `tests/`（全量）

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（Task 4 后：settings 少 2 = 63 个原 + 新增 work_dir 相关 2+2+3 = ~70 个，以实际为准；不得有 FAIL）

- [ ] **Step 2: 清理检查**

Run: `grep -rn "work_dir" shadowtalk/ tests/ | grep -v __pycache__`
Expected: 仅数据层/对话框/L3/worker/main_window 的预期引用，无 Settings/settings_dialog 残留，无死代码

- [ ] **Step 3: 提交（如有遗漏）**

```bash
git add -A
git commit -m "test: verify friend workdir regression" --allow-empty
```

注意：`git add -A` 前先 `git status` 确认没有误带 `../aiworkspace15/`、`.pyc`、`ui*.PNG` 等无关文件；有则只 add 本计划涉及路径。
