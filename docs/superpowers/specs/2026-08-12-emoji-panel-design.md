# 表情面板（Emoji Panel）设计

日期：2026-08-12
状态：已获用户批准（方案 A：内嵌展开式面板，Unicode emoji，一组常用表情）

## 背景

ShadowTalk 聊天输入区目前只有文本输入框 + 发送按钮。用户希望像微信那样，能在聊天输入时插入表情。经确认：使用 **Unicode emoji**（字符形式，非图片表情包），**弹出式内嵌面板**（非浮窗），**一组约 48 个常用表情**（非分类标签页）。

## 设计目标

- 点击输入框旁的笑脸按钮，在输入框上方展开/收起表情网格
- 点击表情插入输入框光标处，可连续点多个表情（面板不自动收起）
- 表情作为普通文本字符走现有消息链路，存储、渲染零改动

## 架构

### 新组件：`shadowtalk/ui/widgets/emoji_panel.py`

`EmojiPanel(QWidget)`：

- **内容**：约 48 个常用 Unicode emoji（笑脸、手势、爱心等），`QGridLayout` 8 列 × 6 行
- **外观**：浅色圆角卡片，与现有配色一致：
  - 背景 `SURFACE`（#FFFFFF），边框 `BORDER`（#E5E2DB），圆角 12px
  - 每个表情格子是扁平按钮，悬停底色 `BG`（#F9F8F6）
  - 表情字号约 20px，按钮尺寸约 38×38
- **信号**：`emoji_selected = Signal(str)` — 点击后发出该 emoji 字符

### 接入：`shadowtalk/ui/widgets/chat_area.py`

1. **笑脸按钮**：输入卡片水平布局（`input_layout`）最左侧加 `QPushButton("😊")`，扁平样式，与发送按钮同一风格，尺寸约 32×32
2. **面板位置**：表情面板加入 `composer_layout`，位于输入卡片**上方**（`insertWidget(0, panel)` 顺序控制），默认 `setVisible(False)`
3. **切换**：点击笑脸按钮 → `panel.setVisible(not panel.isVisible())`；面板打开时按钮底色变化提示激活态
4. **插入**：面板 `emoji_selected` 信号 → `self.input_box.setFocus()` → `textCursor().insertText(emoji)`；面板不收起
5. **点击外部收起**：`ChatArea.eventFilter` 检测全局点击（`QEvent.MouseButtonPress`），若目标不在面板/笑脸按钮内则收起

### 数据流

```
点击表情 → insertText(emoji 字符) → 输入框文本
→ 发送 toPlainText() → MessageRepository 存储（纯文本）
→ MessageBubble/SpeechBubble(QLabel) 渲染（Qt 自动渲染 emoji）
```

- 表情即文本，消息链路**零改动**
- 历史消息中的 emoji 同样自动渲染，无需迁移

## 边界与异常处理

- 点击表情时输入框未聚焦：`insertText` 前先 `setFocus()` + `moveCursor(End)`
- 表情为系统字符，无加载失败路径
- Enter 发送逻辑不受面板状态影响
- 面板展开占据输入区上方的纵向空间（composer_wrap 内部展开），输入卡片与发送逻辑不受影响；消息列表位于其上，其上方空间由 QSplitter/布局自动分配，无挤压异常

## 测试

- 手动：打开面板 → 点表情 → 插入光标处 → 连续点多个 → 发送 → 气泡显示 emoji → 重新打开会话历史消息仍正确显示 → 点击面板外区域面板收起
- 单元测试（可选）：`EmojiPanel` 点击发出 `emoji_selected` 信号且值为对应字符；面板初始不可见

## 范围外（YAGNI）

- 图片表情包 / 大表情
- 表情分类标签页
- 最近使用 / 搜索表情
- 浮窗式面板
