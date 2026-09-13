# ShadowTalk 影聊

**本机优先的 AI 桌面聊天应用** —— 与 AI "好友" 在沉浸式主题房间中对话，拥有长期记忆、AI 工具沙箱、邮件同步数字分身、TTS 语音朗读、英语练习等功能。

> 版本：1.4.1 · 许可证：MIT · 平台：Windows / Linux

---

## ✨ 功能特性

- **沉浸式主题房间** —— 咖啡馆、音乐室、阅读室、英语教室，每个房间拥有独立背景与场景提示词，对话历史与主聊天共享
- **AI 好友系统** —— 为每个 AI 角色设定人设、工作目录、自定义系统提示词
- **长期记忆引擎** —— 四层上下文架构（L3 人设 → L2 高层摘要 → L1 批次摘要 → L0 原始消息），自动归档与摘要压缩
- **AI 工具沙箱** —— AI 可在隔离子进程中执行 Python 代码，双层防护（静态 AST 扫描 + 运行时审计钩子）保障安全
- **数字分身邮件同步** —— 通过 SMTP/IMAP 将聊天摘要打包为邮件发送，接收回复并匹配会话
- **数字资产加密** —— 纯 Python 实现 AES-128-CTR + HMAC-SHA256，保护数字分身资产包
- **TTS 语音朗读** —— 基于 edge-tts 的异步语音合成
- **英语练习工具** —— 内置英语练习与进度追踪
- **明暗主题** —— 全局 QSS 主题系统，支持浅色/深色切换
- **国际化** —— 简体中文界面（i18n 框架已就绪）

---

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| UI 框架 | PySide6 (Qt6) |
| AI 后端 | OpenAI 兼容 API（默认 DeepSeek） |
| 数据库 | SQLite（WAL 模式） |
| 语音 | edge-tts |
| 构建 | PyInstaller（Windows 单文件 / Linux .deb） |
| 测试 | pytest |

---

## 📁 项目结构

```
shadowtalk/
├── config/            # 路径、设置、日志、国际化
│   ├── paths.py       #   路径解析（开发/打包环境自适应）
│   ├── settings.py    #   应用配置读写
│   ├── i18n.py        #   国际化
│   └── app_logger.py  #   日志配置
├── core/              # 业务逻辑（纯 Python，不依赖 PySide6）
│   ├── memory_engine.py     #   四层记忆引擎
│   ├── archiver.py          #   消息归档
│   ├── summarizer.py        #   摘要生成
│   ├── layers/              #   上下文层级实现
│   ├── python_executor.py   #   AI 工具沙箱执行器
│   ├── sandbox_prelude.py   #   运行时审计钩子
│   ├── ai_client.py         #   OpenAI 兼容客户端
│   ├── tts_service.py       #   TTS 语音服务
│   ├── room_service.py      #   房间系统
│   ├── friend_service.py    #   好友管理
│   ├── crypto_service.py    #   资产加密
│   ├── aes_core.py          #   AES 纯 Python 实现
│   ├── mail_*.py            #   邮件同步（作曲/发送/接收/调度/撤销）
│   ├── token_budget.py      #   令牌预算
│   └── background_scanner.py#   后台扫描（L1→L2 合并）
├── data/              # 数据层
│   ├── database.py    #   SQLite 单例连接 + 自动迁移
│   └── repositories.py#   数据访问
├── ui/                # 界面层
│   ├── main_window.py #   主窗口
│   ├── theme.py       #   主题系统（纯数据，不导入 Qt）
│   ├── threads/       #   QThread 工作线程
│   └── widgets/       #   自定义控件
├── models/            # 数据模型
└── workdir/           # 工作目录模板
```

**分层依赖规则**：`ui/` → `core/` → `data/` → `config/`，依赖只能向下流动。`core/` 与 `data/` 禁止导入 `ui/` 或 PySide6。

---

## 🚀 快速开始

### 环境要求

- Python 3.11 或更高版本
- Windows 10+ 或 Linux

### 安装与运行

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 安装依赖
# Windows
venv\Scripts\pip install -r requirements.txt
# Linux
./venv/bin/pip install -r requirements.txt

# 3. 运行应用
# Windows
venv\Scripts\python shadowtalk\main.py
# Linux
./venv/bin/python shadowtalk/main.py
```

### 配置 AI 后端

首次启动后，在设置中填入 OpenAI 兼容 API 的地址与密钥（默认适配 DeepSeek）。

---

## 🧪 测试

```bash
# 运行全部测试（排除需要显示环境的 GUI 测试）
python -m pytest tests -q --ignore=tests/test_main_window.py

# 运行单个测试文件
python -m pytest tests/test_ai_client.py -v

# 运行单个测试函数
python -m pytest tests/test_database.py::TestDatabase::test_something -v
```

测试使用 pytest，通过 `conftest.py` 为每个测试创建独立的临时 SQLite 数据库（autouse fixture）。

---

## 📦 构建发布

### Windows 单文件 exe

```bash
build_exe.bat
```

流程：运行测试 → PyInstaller 打包（`ShadowTalk.spec`）→ 输出 `dist/ShadowTalk.exe`。
spec 文件会打包 Python 3.11 运行时（用于 AI 工具子进程）和 `sandbox_prelude.py`。

### Linux .deb 包

```bash
./build_deb.sh [版本号]
```

需在目标架构的 Linux 上运行。输出 `onedir` 结构 + `.deb` 包，数据目录位于 `~/.shadowtalk`。

---

## 📖 文档

- 用户手册（中文）：[docs/user_manual.md](docs/user_manual.md)
- 用户手册（英文）：[docs/user_manual_en.md](docs/user_manual_en.md)
- 开发指南：[CLAUDE.md](CLAUDE.md)

---

## 📄 许可证

[MIT License](LICENSE) © 2026 test20250718
