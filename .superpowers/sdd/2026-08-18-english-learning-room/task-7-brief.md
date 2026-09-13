# Task 7: UI — exercise card rendering (all 5 types)

**Files to modify:**
- `shadowtalk/ui/widgets/english_room.py` (replace placeholder with real rendering)
- `tests/test_english_room.py` (add tests for each card type)

**What to do:**

Replace the `_render_exercise_card` placeholder in `english_room.py` with real rendering for all 5 exercise types. The `ExerciseCard` class should be expanded to handle each type.

**Card rendering logic:**

1. **`sentence_build` (拖拽组句)**:
   - Show `words` as clickable chip buttons in a "word pool" area
   - Show a "build area" where placed chips appear in order
   - Click chip in pool → moves to build area; click chip in build area → returns to pool
   - "检查答案" button compares build order to `correct_order`
   - "提示" button highlights first correct word
   - "跳过" button skips

2. **`cloze` (选词填空)**:
   - Show `prompt` with `____` placeholder
   - Show `options` as clickable buttons (4 options)
   - Click option → fills the blank, enables "检查答案"
   - Compare selected option to `answer`

3. **`match` (闪电配对)**:
   - Show left column (English words) and right column (Chinese meanings)
   - Click left item then right item to pair
   - Timer counts down from `time_limit` (15s)
   - All pairs matched → auto-submit

4. **`translate_assemble` (翻译拼装)**:
   - Show Chinese `prompt`
   - Show English `words` as clickable chips (includes distractors)
   - Click chips in order to build translation
   - Compare to `correct_order`

5. **`story` (故事分支)**:
   - Show `story_text` (English narrative)
   - Show `choices` as radio buttons or clickable options
   - Select answer → enable "检查答案"
   - Compare to `answer`

**Answer checking flow (all types):**
```python
def _check_answer(self, card, data, user_answer):
    if card._answered:
        return
    card._answered = True
    card._attempts += 1
    correct_answer = data.get("answer", "")
    correct = user_answer.strip().lower() == correct_answer.strip().lower()
    time_used = time.time() - card._start_time
    is_bonus = data.get("is_bonus", False)
    
    # 落库
    record_exercise(self.friend_id, data.get("word", ""),
                   data.get("type", ""), correct,
                   card._attempts, time_used, is_bonus)
    upsert_progress(self.friend_id, self._word_range,
                   data.get("word", ""), correct)
    
    # 显示反馈
    self._show_feedback(card, correct, correct_answer, data.get("explanation", ""))
    
    # 回传 AI
    result = {
        "correct": correct,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "attempts": card._attempts,
        "time_used": time_used,
        "exercise_type": data.get("type", ""),
        "skipped": False,
    }
    if self.ai_worker is not None:
        self.ai_worker.resume_exercise(json.dumps(result))
    
    self._update_stats()
    # 启用输入条
    self.input_edit.setEnabled(True)
    self.send_btn.setEnabled(True)
```

**Skip flow:**
```python
def _skip_exercise(self, card, data):
    if card._answered:
        return
    card._answered = True
    result = {
        "correct": False, "user_answer": "", "correct_answer": data.get("answer", ""),
        "attempts": 0, "time_used": 0, "exercise_type": data.get("type", ""),
        "skipped": True,
    }
    if self.ai_worker is not None:
        self.ai_worker.resume_exercise(json.dumps(result))
    self.input_edit.setEnabled(True)
    self.send_btn.setEnabled(True)
```

**Feedback display:**
```python
def _show_feedback(self, card, correct, correct_answer, explanation):
    """在卡片中显示答题反馈"""
    # 清除旧反馈
    # 对 → 绿色高亮 + 解析；错 → 红框 + 正确答案
    feedback = QLabel()
    if correct:
        feedback.setText(f"✅ 正确！\n{explanation}")
        feedback.setStyleSheet("color: #2E9E57; font-size: 13px; padding: 8px;")
    else:
        feedback.setText(f"❌ 错误。正确答案：{correct_answer}\n{explanation}")
        feedback.setStyleSheet("color: #D9534F; font-size: 13px; padding: 8px;")
    card._layout.addWidget(feedback)
```

**Tests to add:**
- Test that each exercise type renders without crashing
- Test that answering correctly calls record_exercise with correct=True
- Test that answering incorrectly calls record_exercise with correct=False
- Test that resume_exercise is called after answering
- Test that skip calls resume_exercise with skipped=True
- Test that input is re-enabled after answering

**Verification:**
- `pytest tests/test_english_room.py -v` → all pass
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: implement all 5 exercise card types with answer checking`

**Context:** Task 6 created the skeleton with a placeholder. This task replaces the placeholder with real card rendering. The `ExerciseCard` class should be expanded to handle each type. The key interaction pattern is:
1. AI calls `present_exercise` → worker suspends → emits `exercise_requested`
2. UI renders card in right panel
3. User interacts (clicks chips/options)
4. User clicks "检查答案" or "跳过"
5. Answer is checked, stats recorded, result sent back via `resume_exercise`
6. Worker resumes, AI sees the result
