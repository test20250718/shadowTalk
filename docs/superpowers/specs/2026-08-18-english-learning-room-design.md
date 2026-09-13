# 英语教室房间设计

**日期**：2026-08-18
**状态**：已确认
**依赖**：沉浸式房间（2026-08-16）、阅读室（2026-08-17）

## 1. 概述

新增"🏫 英语教室"沉浸式房间，左侧窄聊天区（280px）+ 右侧 AI 驱动的练习卡片面板。
AI 作为一对一英语教师，通过 `present_exercise` 工具在右侧面板中出示结构化练习题，
用户答题后结果回传 AI，AI 据此讲解和动态调整教学。

核心体验：多邻国式的低输入、高互动、即时反馈。全程零键盘输入（点击/拖拽为主）。

## 2. 架构

### 2.1 文件清单

| 文件 | 类型 | 职责 |
|---|---|---|
| `shadowtalk/ui/widgets/english_room.py` | 新增 | `EnglishRoomWindow(RoomWindow)`：左聊右练布局；拦截工具调用渲染卡片；答题回传 |
| `shadowtalk/core/english_exercise.py` | 新增 | 练习引擎：工具 JSON Schema 定义、答题判定、统计读写、词库进度管理 |
| `shadowtalk/data/database.py` | 修改 | 新增 `english_exercise_stats` 和 `english_progress` 表；`_migrate` 播种 `english` 房间 |
| `shadowtalk/ui/main_window.py` | 修改 | 房间选择对话框加"🏫 英语教室"；实例化 `EnglishRoomWindow` |
| `shadowtalk/ui/widgets/room_window.py` | 修改 | `_ROOM_ICONS` 加 `"english": "🏫"` |
| `shadowtalk/core/ai_client.py` | 修改 | `chat_with_tools` 工具列表注入 `present_exercise` |
| `shadowtalk/core/python_executor.py` | 修改 | 工具路由加 `present_exercise` 分支（挂起等待用户交互） |

### 2.2 布局结构

```
EnglishRoomWindow(RoomWindow)
├── 顶栏（复用 RoomWindow）：标题 + 学习统计 + 换背景/词库/离开
├── _content_host（窄 + 宽）
│   ├── chat_scroll（280px，左）：复用 RoomBubble 聊天
│   └── exercise_panel（右，自适应）：练习卡片 + 进度条
├── _pre_input_host（复用）：可扩展提示条
└── 输入条（复用 RoomWindow）
```

与阅读室（左书右聊）镜像：英语教室是左聊右练。

## 3. 题型设计

### 3.1 题型一览

| type 值 | 名称 | 交互 | 考查点 | 数据结构 |
|---|---|---|---|---|
| `sentence_build` | 拖拽组句 | 点击/拖拽单词 chip 排列成正确语序 | 语序、语法结构 | `words` + `correct_order` |
| `cloze` | 选词填空 | 从候选词（含干扰项）点击填入句中空白 | 词汇辨析、搭配 | `prompt`(含`____`) + `options` + `answer` |
| `match` | 闪电配对 | 限时 15 秒配对消除中英文 | 词义记忆 | `pairs` + `time_limit` |
| `translate_assemble` | 翻译拼装 | 给中文，从英文 chip（含干扰词）按序点击组句 | 翻译 + 语序 | `prompt`(中文) + `words` + `correct_order` |
| `story` | 故事分支 | AI 讲 2-3 句英文情节，点击选项续写 | 阅读理解 + 推理 | `story_text` + `choices` + `answer` |

### 3.2 交互规则

- **chip 点击**：单词池 chip → 构建区（左→右排列）；构建区 chip → 回池子（可修改）
- **检查答案**：对 → 绿色高亮 + 飞入解析；错 → 红框抖动 + 显示正确顺序
- **提示**：高亮第一个正确位置的单词
- **跳过**：直接显示答案，标记为"跳过"（不计入正确率）
- **答完过渡**：展示解析 + AI 回复 + [再来一题] / [继续聊天] 按钮

### 3.3 拖拽增强（后续优化）

首版实现点击排序（tap-to-build），后续可加 QDrag/QDrop 拖拽。两种交互共存：点击优先，拖拽可选。

## 4. 工具协议

### 4.1 present_exercise 工具定义

```python
{
    "name": "present_exercise",
    "description": "给用户出一道英语练习题。当用户进入练习模式、答完上一题继续、或你判断需要巩固某个知识点时调用。",
    "parameters": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["sentence_build", "cloze", "match", "translate_assemble", "story"]
            },
            "word": {"type": "string"},                    # 考查的目标词
            "prompt": {"type": "string"},                 # 题干/提示
            "words": {"type": "array", "items": {"type": "string"}},  # chip 单词列表
            "correct_order": {"type": "array", "items": {"type": "integer"}},  # 正确索引序
            "options": {"type": "array", "items": {"type": "string"}},  # 填空候选词
            "answer": {"type": "string"},                 # 正确答案
            "pairs": {"type": "object", "additionalProperties": {"type": "string"}},  # 配对
            "time_limit": {"type": "integer"},            # 限时秒数
            "story_text": {"type": "string"},             # 故事叙述
            "choices": {"type": "array", "items": {"type": "string"}},  # 故事选项
            "explanation": {"type": "string"}             # 答案解析
        },
        "required": ["type", "word", "answer", "explanation"]
    }
}
```

### 4.2 工具挂起与恢复机制

`python_executor` 的 `execute_tool()` 对 `present_exercise` 不执行代码，
而是抛出 `ToolSuspendError(payload=tool_args)` 中断当前工具执行循环。
`AIWorker` 捕获此异常后发射 `exercise_requested` 信号，`EnglishRoomWindow`
渲染卡片并禁用输入条。答题后 `EnglishRoomWindow` 调用
`AIWorker.resume_exercise(tool_call_id, result_json)`，将答题结果注入
`chat_with_tools` 的工具结果队列，恢复 AI 对话流。

### 4.3 答题结果回传

答题后生成标准 tool_result 回传给 AI：

```python
{
    "role": "tool",
    "tool_call_id": "<原调用 id>",
    "content": json.dumps({
        "correct": True | False,
        "user_answer": "用户答案/选项/配对结果",
        "correct_answer": "正确答案",
        "attempts": 1,
        "time_used": 8.5,
        "exercise_type": "sentence_build",
        "skipped": False
    })
}
```

AI 根据 `correct` + `attempts` 决定讲解深度和下一步。

## 5. AI 教学引擎

### 5.1 场景人设（scene_prompt）

```
你是一位专业的英语一对一教师，正在使用 {word_range} 词库系统性地辅导学生。
（当前词库：{word_range}；当前进度：已掌握 {mastered} 词，学习中 {learning} 词，待复习 {review_due} 词）

教学原则：
- 系统性：按词库范围有计划地推进，确保覆盖核心词汇，不跳跃
- 间隔重复：根据答题记录，在快要遗忘时安排复习（错过的词在 1/3/7 轮后重现）
- 难度递进：先词义辨识 → 再填空 → 再组句 → 最后翻译拼装，同一词汇螺旋上升
- 自由对话是语境补充：从上下文了解学生兴趣和表达水平，但出题围绕词库进度
- 用 present_exercise 工具出题，等学生答题后再讲解
- 讲解简洁有力，1-3 句话
- 偶尔可以"超纲"出 1-2 道拓展题（标注为 bonus），但不影响进度统计
```

### 5.2 AI 决策逻辑

| 触发条件 | AI 行为 |
|---|---|
| 进入房间 / 进度恢复 | 从进度表取"下一个待学词"；先复习标记为"需复习"的旧词 |
| 用户说"出题/练习/考考我" | 立即按计划出题 |
| 对话中遇到词库内的词 | 作为切入点出题（自然语境），进度表顺延 |
| 对话中遇到相关超纲词 | 可"顺手"出 1 道拓展题（bonus，不计入考核） |
| 用户连续答对 3 题 | 加速推进 / 出彩蛋拓展题 |
| 用户答错 | 词标记"需复习"，安排 1/3/7 轮后再现；降级同类题型再练 |
| 用户说"继续聊/不练了" | 停止出题，自由对话，进度保留 |

### 5.3 出题优先级

```
默认：review_at <= now（该复习） > status='learning'（正在学） > status='new'（新词）

灵活调整（AI 自主判断）：
+ 对话中自然出现的词库词 → 提前出
+ 学生表现好 → 偶尔出超纲拓展题（bonus，不计错题统计）
+ 学生状态差 → 回头复习已掌握词找回信心
```

## 6. 词库与水平定级

### 6.1 词库选择

进入房间时的词库配置对话框：

| 词库 | 词汇量 | 说明 |
|---|---|---|
| CET-4 | ~4500 | 大学英语四级，日常/学术/社会基础词汇 |
| CET-6 | ~5500 | 大学英语六级，进阶词汇与表达 |
| IELTS | ~6000 | 雅思核心，学术与移民场景 |
| TOEFL | ~8000 | 托福核心，学术英语深入 |

### 6.2 快速定级测试

用户可选"快速测试后定级"：AI 出 5 道递进难度题（易→难），根据正确率决定起始进度：
- 5/5 → 从 30% 进度开始
- 3-4/5 → 从 15% 进度开始
- 0-2/5 → 从头开始

### 6.3 AI 词库边界控制

由于不内置词库文件（AI 动态生成），在系统 prompt 中注入等级描述 + 50-100 个示例词，
让 AI 理解该等级的词汇范围和难度边界。出题偶尔超纲（bonus）但不影响进度。

### 6.4 进度表初始化

AI 每次调用 `present_exercise` 时，`english_exercise.handle()` 在落库答题记录前，
先检查该词是否已在 `english_progress` 表中：
- 不存在 → INSERT（status='learning'，按 AI 返回的 word 作为主词）
- 已存在 → 根据答题结果 UPDATE（correct 累加 times_correct，wrong 累加 times_wrong，
  按 1/3/7 轮规则更新 review_at，连续 3 次 correct 升级 status 至 'mastered'）

首次进入房间时进度表为空，AI 根据词库等级描述自主选词，逐次填充。
无需预加载词库，进度随使用自然积累。

## 7. 数据模型

### 7.1 english_exercise_stats（答题记录）

```sql
CREATE TABLE english_exercise_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    exercise_type TEXT NOT NULL,
    correct BOOLEAN NOT NULL,
    attempts INTEGER DEFAULT 1,
    time_used REAL,
    is_bonus BOOLEAN DEFAULT 0,     -- 超纲拓展题（不计入考核）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
```

### 7.2 english_progress（学习进度）

```sql
CREATE TABLE english_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    word_range TEXT NOT NULL,       -- 'CET-4' / 'CET-6' / 'IELTS' / 'TOEFL'
    word TEXT NOT NULL,
    status TEXT NOT NULL,           -- 'new' / 'learning' / 'review' / 'mastered'
    review_at TEXT,                 -- 下次复习时间 (ISO datetime)
    times_correct INTEGER DEFAULT 0,
    times_wrong INTEGER DEFAULT 0,
    last_exercise_at DATETIME,
    PRIMARY KEY (friend_id, word_range, word),
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
```

### 7.3 rooms 表播种

```python
conn.execute(
    "INSERT OR IGNORE INTO rooms (key, name, scene_prompt) "
    "VALUES ('english', '英语教室', ?)",
    (_ENGLISH_SCENE_PROMPT,)
)
conn.execute("UPDATE rooms SET scene_prompt=? WHERE key='english'",
             (_ENGLISH_SCENE_PROMPT,))
```

## 8. 统计展示

顶栏标题区固定显示：
```
🔥 连胜: N  |  今日: N 题  |  正确率: N%
```

统计查询：
- **连胜**：从最近一条倒序数连续 correct=true 的数量
- **正确率**：最近 50 题（不含 bonus）的 correct 比例
- **今日已练**：COUNT WHERE date(created_at) = today AND is_bonus=0
- **高频错词**：GROUP BY word ORDER BY SUM(correct=false) DESC

## 9. 数据流总览

```
用户发消息 → AI 决定出题 → 调用 present_exercise(JSON)
    ↓
python_executor 路由到 english_exercise.handle()
    ↓
抛出 ToolSuspendError(payload) → AIWorker 捕获
    ↓
发射 exercise_requested 信号 → EnglishRoomWindow 渲染卡片（输入条禁用）
    ↓
用户答题 → EnglishRoomWindow 判定对错 → stats 落库 + progress 更新
    ↓
调用 AIWorker.resume_exercise(tool_call_id, result_json)
    ↓
tool_result 注入对话流 → AI 恢复生成
    ↓
AI 看 correct/attempts → 讲解/调整难度/继续对话
```

## 10. 待确认与后续

- [ ] 拖拽交互（首版点击排序，拖拽作为后续优化）
- [ ] 错题本间隔重复（当前仅标记 review_at，完整艾宾浩斯实现后续）
- [ ] 词库切换时的进度隔离（每个 word_range 独立进度）
- [ ] 音效反馈（对/错/连胜，后续可加）
- [ ] 学习报告（周/月统计视图，后续可加）
