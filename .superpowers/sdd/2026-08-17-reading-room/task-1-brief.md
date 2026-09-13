### Task 1: reading_service 纯函数（章节反查 + 滑动窗口）

**Files:**
- Create: `shadowtalk/core/reading_service.py`
- Test: `tests/test_reading_service.py`

**Interfaces:**
- Consumes: 无（纯函数，不依赖 Qt/pypdf）
- Produces（Task 3/7 依赖）:
  - `find_chapter_title(page_text: Callable[[int], str], page: int, max_back: int = 10) -> str`（1 基页码；空串=没找到）
  - `build_window_text(page_text: Callable[[int], str], page: int, page_count: int, before: int = 4) -> str`（全部页空 → `""`；个别空页 → `（第N页无法提取）` 占位）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_reading_service.py`：

```python
"""阅读室服务测试：章节反查、滑动窗口（纯函数部分）"""
import sys
from pathlib import Path

import pytest

from shadowtalk.data.database import Database
from shadowtalk.data.repositories import FriendRepository

Database.get_connection()   # 触发迁移（Task 2 会加 reading_progress）

BOOK = Path(r"C:\work\aiworkspace12\novels\PDF合集\西游记的正确打开方式.pdf")
needs_book = pytest.mark.skipif(not BOOK.is_file(), reason="本机无目标书")


def _make_friend(name="小读"):
    return FriendRepository.insert(name, "", "你是小读")


# ── 章节反查 ──

def test_chapter_title_found_on_same_page():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {5: "第2章 寿命即货币\n满堂议论声嗡嗡作响。"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 5) == "第2章 寿命即货币"


def test_chapter_title_scan_backward():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {10: "第1章 开端\n正文", 15: "正文若干" * 50}
    assert find_chapter_title(lambda p: pages.get(p, ""), 15) == "第1章 开端"


def test_chapter_title_prefers_chapter_over_volume():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {8: "第一卷：三界资本格局构建\n第1章 说书人开讲\n正文"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 9) == "第1章 说书人开讲"


def test_chapter_title_volume_only_fallback():
    from shadowtalk.core.reading_service import find_chapter_title
    pages = {8: "第一卷：三界资本格局构建\n正文"}
    assert find_chapter_title(lambda p: pages.get(p, ""), 9) == "第一卷：三界资本格局构建"


def test_chapter_title_not_found_returns_empty():
    from shadowtalk.core.reading_service import find_chapter_title
    assert find_chapter_title(lambda p: "正文" * 100, 50) == ""


# ── 滑动窗口 ──

def test_window_text_joins_pages():
    from shadowtalk.core.reading_service import build_window_text
    pages = {96: "甲", 97: "乙", 98: "丙", 99: "丁", 100: "戊"}
    assert build_window_text(lambda p: pages.get(p, ""), 100, 360) == "甲\n乙\n丙\n丁\n戊"


def test_window_text_clamps_at_first_page():
    from shadowtalk.core.reading_service import build_window_text
    assert build_window_text(lambda p: f"P{p}", 2, 360) == "P1\nP2"


def test_window_text_marks_failed_pages():
    from shadowtalk.core.reading_service import build_window_text
    pages = {1: "有字"}
    text = build_window_text(lambda p: pages.get(p, ""), 3, 360)
    assert "（第2页无法提取）" in text
    assert "（第3页无法提取）" in text
    assert text.startswith("有字")


def test_window_text_all_empty_for_scan():
    from shadowtalk.core.reading_service import build_window_text
    assert build_window_text(lambda p: "", 100, 360) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: FAIL（`ModuleNotFoundError: shadowtalk.core.reading_service`）

- [ ] **Step 3: 写实现**

新建 `shadowtalk/core/reading_service.py`（本任务只写两个纯函数 + 常量，其余 Task 2/3 再加）：

```python
# shadowtalk/core/reading_service.py
"""阅读室服务：PDF 文本提取（懒加载）、章节标题反查、滑动窗口组装、
共读进度存取。

按需阅读（设计 2026-08-17）：用户翻页她不读不语；发问时才现场组装
"当前页+前几页+章节标题"进场景上下文。零预读、零翻页监听。
"""
import re

# 章节标题：页首出现的「第X章/回/节/卷 标题」整行
_CHAPTER_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千零两]+[章回节卷][^\n]{0,30})$", re.M)
_FINE_LEVELS = ("章", "回", "节")   # 粒度优先于「卷」
_SCAN_HEAD_CHARS = 600              # 只在页首找标题
_MAX_BACK_PAGES = 10                # 章节反查最多回看页数
_WINDOW_BEFORE = 4                  # 滑动窗口：当前页往前几页


def find_chapter_title(page_text, page: int,
                       max_back: int = _MAX_BACK_PAGES) -> str:
    """从 page 页起往回找最近的章节标题；找不到返回空串。

    page_text: (1 基页码) -> 该页文本。同一页既有「章/回/节」又有
    「卷」时取前者（更细粒度）；同页多条取最后一条（最靠近正文）。
    """
    for p in range(page, max(1, page - max_back) - 1, -1):
        head = page_text(p)[:_SCAN_HEAD_CHARS]
        matches = _CHAPTER_RE.findall(head)
        fine = [m for m in matches if any(k in m for k in _FINE_LEVELS)]
        if fine:
            return fine[-1].strip()
        if matches:
            return matches[-1].strip()
    return ""


def build_window_text(page_text, page: int, page_count: int,
                      before: int = _WINDOW_BEFORE) -> str:
    """滑动窗口：第 page-before..page 页正文连排。

    全部页都提不到文本 → 空串（调用方按扫描件处理）；
    个别空页以「（第N页无法提取）」占位。
    """
    parts, any_text = [], False
    for p in range(max(1, page - before), page + 1):
        if p > page_count:
            break
        t = page_text(p).strip()
        if not t:
            parts.append(f"（第{p}页无法提取）")
        else:
            any_text = True
            parts.append(t)
    return "\n".join(parts) if any_text else ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_reading_service.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/reading_service.py tests/test_reading_service.py
git commit -m "feat: reading service chapter lookup and sliding window text"
```

