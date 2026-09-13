# Task 9: Scene prompt injection with word_range and stats

**Files to modify:**
- `shadowtalk/core/english_exercise.py` (add `build_scene_prompt`)
- `shadowtalk/ui/widgets/english_room.py` (use it)
- `tests/test_english_exercise.py` (add tests)

**What to do:**

1. **Add `build_scene_prompt` function** to `shadowtalk/core/english_exercise.py`:

```python
def build_scene_prompt(friend_id: int, word_range: str) -> str:
    """构建带词库范围和当前统计的场景 prompt"""
    conn = Database.get_connection()
    mastered = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='mastered'",
        (friend_id, word_range)).fetchone()[0]
    learning = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='learning'",
        (friend_id, word_range)).fetchone()[0]
    now = datetime.datetime.now().isoformat()
    review_due = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND review_at IS NOT NULL "
        "AND review_at <= ?",
        (friend_id, word_range, now)).fetchone()[0]

    return _SCENE_PROMPT_TEMPLATE.format(
        word_range=word_range,
        mastered=mastered,
        learning=learning,
        review_due=review_due,
    )


_SCENE_PROMPT_TEMPLATE = """你是一位专业的英语一对一教师，正在使用 {word_range} 词库辅导学生。

当前进度：已掌握 {mastered} 词，学习中 {learning} 词，待复习 {review_due} 词。

教学原则：
- 系统性：按词库范围有计划地推进，确保覆盖核心词汇
- 间隔重复：根据答题记录，错过的词在 1/3/7 轮后重现
- 难度递进：先词义辨识，再填空，再组句，最后翻译拼装
- 自由对话是语境补充：从上下文了解学生兴趣和表达水平
- 用 present_exercise 工具出题，等学生答题后再讲解
- 讲解简洁有力，1-3 句话
- 偶尔可以超纲出 1-2 道拓展题（标注为 bonus），但不影响进度统计"""
```

2. **Override `_current_scene_prompt`** in `english_room.py`:

```python
    def _current_scene_prompt(self) -> str:
        from shadowtalk.core.english_exercise import build_scene_prompt
        return build_scene_prompt(self.friend_id, self._word_range)
```

3. **Add tests** to `tests/test_english_exercise.py`:

```python
def test_build_scene_prompt_injects_word_range():
    """build_scene_prompt 应将词库范围注入场景描述"""
    from shadowtalk.core.english_exercise import build_scene_prompt
    prompt = build_scene_prompt(1, "CET-6")
    assert "CET-6" in prompt
    assert "英语" in prompt


def test_build_scene_prompt_injects_stats():
    """build_scene_prompt 应注入当前进度统计"""
    from shadowtalk.core.english_exercise import build_scene_prompt
    prompt = build_scene_prompt(1, "IELTS")
    assert "掌握" in prompt
```

**Verification:**
- `pytest tests/test_english_exercise.py -v -k "scene_prompt"` → PASS
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: inject word range and stats into english room scene prompt`

**Context:** The scene prompt is inserted into the AI context by `build_room_context()` (in `room_service.py`) right after the L3 persona block. By overriding `_current_scene_prompt()`, the English room dynamically injects the current word range and learning progress into the system prompt, so the AI always knows what it's teaching and how the student is doing.
