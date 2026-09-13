# SDD ledger — plan: docs/superpowers/plans/2026-08-17-reading-room.md

## 基线（2026-08-17）
- worktree: C:\work\.claude\worktrees\reading-room（分支 worktree-reading-room，基于 video-workbench@26414b3）
- 基线测试：240 passed（`python -m pytest tests/ --ignore=tests/test_main_window.py`，48s）
- 已知问题（预先存在，非本计划范围）：tests/test_main_window.py 全量运行时原生段错误（exit 139，单测通过/顺序触发，原工作区同样复现）。全量回归口径 = 忽略该文件。
- 执行注意：计划文本中的工作目录 c:\work\aiworkspace18 一律以 worktree 内 aiworkspace18 为准。

Task 1: complete (commits 26414b3..512b19d, review clean)
Task 1: minor (deferred): tests 里 import sys 未用（计划脚手架自带，Task 2/3 改此文件时可顺手删）
Task 1: minor (deferred): 章节"精细粒度"用子串包含判定，卷标题含"章/回/节"字样会误判（计划自带启发式，影响限同页标题选择）
