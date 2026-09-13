# tools/recover_from_logs.py
"""
ShadowTalk 数据恢复与迁移工具

功能：
1. 从提示词日志恢复好友数据到数据库
2. 导出好友数据到 txt 文件（可跨电脑迁移）
3. 从 txt 文件导入好友数据到数据库

使用方法：直接双击运行，或 python tools/recover_from_logs.py
"""
import os
import re
import sys
import sqlite3
import tkinter as tk
from tkinter import messagebox, filedialog
from pathlib import Path


# ── 日志解析 ──

def find_logs_base() -> Path:
    """定位日志根目录"""
    candidates = [
        Path.cwd() / "logs" / "chat_prompts",
        Path(sys.executable).parent / "logs" / "chat_prompts"
        if getattr(sys, "frozen", False) else Path(),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def scan_friends(logs_dir: Path) -> list[dict]:
    """扫描日志目录，返回 [{name, id, log_count, last_time}]"""
    friends = []
    for entry in sorted(logs_dir.iterdir()):
        if not entry.is_dir():
            continue
        m = re.match(r"^(.+?)_(\d+)$", entry.name)
        if not m:
            continue
        name, fid = m.group(1), int(m.group(2))
        log_files = sorted(entry.glob("*.log"))
        if not log_files:
            continue
        last_time = log_files[-1].stem
        friends.append({
            "name": name, "id": fid, "folder": entry.name,
            "log_count": len(log_files), "last_time": last_time,
        })
    return friends


def parse_l3_persona(content: str) -> dict:
    """从 L3 system 内容解析 ai_role / user_role / work_dir / system_prompt"""
    result = {"ai_role": "", "user_role": "", "work_dir": "", "system_prompt": ""}
    if not content:
        return result
    m = re.search(r"^你是(.+?)。", content, re.MULTILINE)
    if m:
        result["ai_role"] = m.group(1).strip()
    m = re.search(r"对方是(.+?)。", content, re.MULTILINE)
    if m:
        result["user_role"] = m.group(1).strip()
    m = re.search(r"你的工作目录是\s*(.+?)。", content)
    if m:
        result["work_dir"] = m.group(1).strip()
    lines = content.split("\n")
    used_indices = set()
    for i, line in enumerate(lines):
        if re.match(r"^你是.+。$", line) or \
           re.match(r"^对方是.+。$", line) or \
           re.match(r"^你的工作目录是.+。$", line):
            used_indices.add(i)
    remaining_lines = [l for i, l in enumerate(lines) if i not in used_indices]
    result["system_prompt"] = "\n".join(remaining_lines).strip()
    return result


def parse_log_file(log_path: Path) -> dict:
    """解析单个日志文件，提取各层内容"""
    text = log_path.read_text(encoding="utf-8")
    result = {"L3": [], "L2": [], "L1": [], "L0": [], "user_message": "", "ai_reply": ""}
    current_layer = None
    lines = text.split("\n")
    for line in lines:
        if line.startswith("【L3 - "):
            current_layer = "L3"
        elif line.startswith("【L2 - "):
            current_layer = "L2"
        elif line.startswith("【L1 - "):
            current_layer = "L1"
        elif line.startswith("【L0 - "):
            current_layer = "L0"
        elif line.startswith("【用户消息 "):
            current_layer = "user_msg"
        elif line.startswith("【AI 回复 "):
            current_layer = "ai_reply"
        elif line.startswith("==="):
            current_layer = None
        elif line.startswith("---"):
            pass  # 层间分隔线，不重置
        elif current_layer in ("L3", "L2", "L1", "L0"):
            m = re.match(r"\s*\[\d+\]\s*role=(\S+)\s*tokens≈\d+", line)
            if m:
                result[current_layer].append({"role": m.group(1), "content": ""})
            elif result[current_layer] and not line.strip().startswith("["):
                content = line.strip()
                if content and content != "（无）":
                    content = content.replace("\\n", "\n")
                    result[current_layer][-1]["content"] = content
        elif current_layer == "user_msg":
            if line.strip() and not line.startswith("tokens") and not line.startswith("---"):
                result["user_message"] = line.strip().replace("\\n", "\n")
        elif current_layer == "ai_reply":
            if line.strip() and not line.startswith("tokens") and not line.startswith("---"):
                result["ai_reply"] += line.strip().replace("\\n", "\n") + "\n"
    result["ai_reply"] = result["ai_reply"].strip()
    return result


# ── 数据库操作 ──

SCHEMA = """
CREATE TABLE IF NOT EXISTS friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    ai_role TEXT DEFAULT '',
    user_role TEXT DEFAULT '',
    work_dir TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    voice TEXT DEFAULT '',
    authorizer_email TEXT DEFAULT '',
    recipient_email TEXT DEFAULT '',
    mail_sync_enable INTEGER DEFAULT 0,
    mail_receiver_address TEXT DEFAULT '',
    mail_sync_cycle TEXT DEFAULT 'daily',
    email_session_id TEXT DEFAULT '',
    last_sent_message_id INTEGER DEFAULT 0,
    last_sent_at TEXT DEFAULT '',
    asset_revoked INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    sender_type TEXT NOT NULL CHECK(sender_type IN ('user','ai','human_reply')),
    content TEXT NOT NULL,
    round_index INTEGER NOT NULL,
    is_archived INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_friend_round ON chat_messages(friend_id, round_index);
CREATE INDEX IF NOT EXISTS idx_messages_archived ON chat_messages(friend_id, is_archived);
CREATE TABLE IF NOT EXISTS batch_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_round INTEGER NOT NULL,
    end_round INTEGER NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_archived INTEGER DEFAULT 0,
    is_truncated INTEGER DEFAULT 0,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_batch_friend_time ON batch_summary(friend_id, create_time);
CREATE INDEX IF NOT EXISTS idx_batch_expired ON batch_summary(friend_id, is_archived, create_time);
CREATE TABLE IF NOT EXISTS high_level_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_high_friend_time ON high_level_summary(friend_id, create_time);
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    scene_prompt TEXT DEFAULT '',
    bg_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS room_backgrounds (
    room_key TEXT NOT NULL,
    friend_id INTEGER NOT NULL,
    bg_path TEXT NOT NULL,
    PRIMARY KEY (room_key, friend_id),
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    friend_id INTEGER,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    action TEXT DEFAULT '',
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
"""


def init_db(db_path: Path):
    """创建空数据库"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.close()


def recover_friend(logs_dir: Path, friend_info: dict, db_path: Path) -> dict:
    """从日志恢复单个好友"""
    folder = logs_dir / friend_info["folder"]
    log_files = sorted(folder.glob("*.log"))

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=OFF")

    stats = {"messages": 0, "persona": False}
    all_l0_messages = []
    seen_contents = set()
    persona = None

    for log_file in log_files:
        parsed = parse_log_file(log_file)
        if not persona and parsed["L3"]:
            persona = parse_l3_persona(parsed["L3"][0]["content"])
            stats["persona"] = True
        for msg in parsed["L0"]:
            key = (msg["role"], msg["content"])
            if msg["content"] and key not in seen_contents:
                seen_contents.add(key)
                all_l0_messages.append(msg)

    if persona:
        conn.execute(
            "INSERT OR REPLACE INTO friends (id, name, remark, ai_role, user_role, "
            "work_dir, system_prompt, avatar_path) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
            (friend_info["id"], friend_info["name"], "",
             persona["ai_role"], persona["user_role"],
             persona["work_dir"], persona["system_prompt"])
        )

    round_idx = 1
    for msg in all_l0_messages:
        sender_type = "ai" if msg["role"] == "assistant" else "user"
        conn.execute(
            "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
            "VALUES (?, ?, ?, ?)",
            (friend_info["id"], sender_type, msg["content"], round_idx)
        )
        stats["messages"] += 1
        if sender_type == "user":
            round_idx += 1

    conn.commit()
    conn.close()
    return stats


# ── 导出/导入文件夹 ──

def export_friends_to_folder(logs_dir: Path, friends_data: list[dict],
                             output_dir: Path, base_dir: Path):
    """导出好友数据到文件夹（含头像、聊天记录 txt、数据库）"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建头像目录
    avatars_dir = output_dir / "avatars"
    avatars_dir.mkdir(exist_ok=True)

    # 导出每个好友
    exported = []
    for fd in friends_data:
        friend_dir = output_dir / f"{fd['name']}_{fd['id']}"
        friend_dir.mkdir(exist_ok=True)

        # 保存人设信息
        info_path = friend_dir / "info.txt"
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(f"ID: {fd['id']}\n")
            f.write(f"NAME: {fd['name']}\n")
            f.write(f"AI_ROLE: {fd['persona']['ai_role']}\n")
            f.write(f"USER_ROLE: {fd['persona']['user_role']}\n")
            f.write(f"WORK_DIR: {fd['persona']['work_dir']}\n")
            f.write(f"SYSTEM_PROMPT: {fd['persona']['system_prompt']}\n")

        # 保存聊天记录
        msgs_path = friend_dir / "messages.txt"
        with open(msgs_path, "w", encoding="utf-8") as f:
            for msg in fd["messages"]:
                f.write(f"[{msg['sender_type']}] {msg['content']}\n")

        # 复制头像（如果有）
        avatar_src = base_dir / "data" / "avatars" / str(fd["id"])
        if avatar_src.exists():
            import shutil
            for img in avatar_src.iterdir():
                if img.is_file():
                    shutil.copy2(img, avatars_dir / f"{fd['id']}_{img.name}")

        exported.append(fd["name"])

    return exported


def import_folders_to_db(input_dir: Path, db_path: Path) -> dict:
    """从文件夹导入好友数据到数据库"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=OFF")
    stats = {"friends": 0, "messages": 0, "avatars": 0}

    # 遍历好友目录
    for entry in sorted(input_dir.iterdir()):
        if not entry.is_dir() or entry.name == "avatars":
            continue
        info_path = entry / "info.txt"
        msgs_path = entry / "messages.txt"
        if not info_path.exists():
            continue

        # 读取人设
        info = {}
        with open(info_path, "r", encoding="utf-8") as f:
            for line in f:
                if ": " in line:
                    k, v = line.strip().split(": ", 1)
                    info[k] = v

        fid = int(info.get("ID", 0))
        fname = info.get("NAME", entry.name)
        if not fid:
            continue

        conn.execute(
            "INSERT OR REPLACE INTO friends (id, name, remark, ai_role, user_role, "
            "work_dir, system_prompt, avatar_path) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
            (fid, fname, "", info.get("AI_ROLE", ""), info.get("USER_ROLE", ""),
             info.get("WORK_DIR", ""), info.get("SYSTEM_PROMPT", ""))
        )

        # 读取消息
        if msgs_path.exists():
            round_idx = 1
            with open(msgs_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip()
                    m = re.match(r"^\[(\w+)\] (.*)$", line, re.DOTALL)
                    if m:
                        sender_type = m.group(1)
                        content = m.group(2)
                        conn.execute(
                            "INSERT INTO chat_messages (friend_id, sender_type, "
                            "content, round_index) VALUES (?, ?, ?, ?)",
                            (fid, sender_type, content, round_idx)
                        )
                        stats["messages"] += 1
                        if sender_type == "user":
                            round_idx += 1

        # 复制头像
        avatars_dir = input_dir / "avatars"
        if avatars_dir.exists():
            import shutil
            dst_avatar_dir = db_path.parent / "data" / "avatars" / str(fid)
            dst_avatar_dir.mkdir(parents=True, exist_ok=True)
            for img in avatars_dir.iterdir():
                if img.is_file() and img.name.startswith(f"{fid}_"):
                    shutil.copy2(img, dst_avatar_dir / img.name)
                    stats["avatars"] += 1

        stats["friends"] += 1

    conn.commit()
    conn.close()
    return stats


# ── 导出/导入 TXT（单文件格式） ──

def export_friends_to_txt(friends_data: list[dict], output_path: Path):
    """导出好友数据到 txt 文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=== ShadowTalk 好友数据导出 ===\n")
        f.write(f"好友数量: {len(friends_data)}\n\n")

        for fd in friends_data:
            f.write(f"---FRIEND---\n")
            f.write(f"ID: {fd['id']}\n")
            f.write(f"NAME: {fd['name']}\n")
            f.write(f"AI_ROLE: {fd['persona']['ai_role']}\n")
            f.write(f"USER_ROLE: {fd['persona']['user_role']}\n")
            f.write(f"WORK_DIR: {fd['persona']['work_dir']}\n")
            f.write(f"SYSTEM_PROMPT: {fd['persona']['system_prompt']}\n")
            f.write(f"---MESSAGES---\n")
            for msg in fd["messages"]:
                f.write(f"[{msg['sender_type']}] {msg['content']}\n")
            f.write("\n")


def collect_friends_data(logs_dir: Path, friends: list[dict]) -> list[dict]:
    """收集好友的完整数据（用于导出）"""
    result = []
    for friend_info in friends:
        folder = logs_dir / friend_info["folder"]
        log_files = sorted(folder.glob("*.log"))
        all_l0_messages = []
        seen_contents = set()
        persona = None

        for log_file in log_files:
            parsed = parse_log_file(log_file)
            if not persona and parsed["L3"]:
                persona = parse_l3_persona(parsed["L3"][0]["content"])
            for msg in parsed["L0"]:
                key = (msg["role"], msg["content"])
                if msg["content"] and key not in seen_contents:
                    seen_contents.add(key)
                    sender_type = "ai" if msg["role"] == "assistant" else "user"
                    all_l0_messages.append({
                        "sender_type": sender_type,
                        "content": msg["content"]
                    })

        if not persona:
            persona = {"ai_role": "", "user_role": "", "work_dir": "", "system_prompt": ""}

        result.append({
            "id": friend_info["id"],
            "name": friend_info["name"],
            "persona": persona,
            "messages": all_l0_messages,
        })
    return result


def import_friends_from_txt(txt_path: Path, db_path: Path) -> dict:
    """从 txt 文件导入好友数据到数据库"""
    text = txt_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=OFF")

    stats = {"friends": 0, "messages": 0}

    # 解析 txt
    friends_blocks = text.split("---FRIEND---")[1:]  # 第一个是空的开头
    for block in friends_blocks:
        lines = block.strip().split("\n")
        fid = None
        fname = ""
        ai_role = ""
        user_role = ""
        work_dir = ""
        system_prompt = ""
        messages = []

        in_messages = False
        for line in lines:
            line = line.rstrip()
            if line.startswith("ID: "):
                fid = int(line[4:])
            elif line.startswith("NAME: "):
                fname = line[6:]
            elif line.startswith("AI_ROLE: "):
                ai_role = line[9:]
            elif line.startswith("USER_ROLE: "):
                user_role = line[10:]
            elif line.startswith("WORK_DIR: "):
                work_dir = line[10:]
            elif line.startswith("SYSTEM_PROMPT: "):
                system_prompt = line[15:]
            elif line == "---MESSAGES---":
                in_messages = True
            elif in_messages and line.startswith("["):
                # [user] xxx 或 [ai] xxx
                m = re.match(r"^\[(\w+)\] (.*)$", line, re.DOTALL)
                if m:
                    messages.append({"sender_type": m.group(1), "content": m.group(2)})

        if fid and fname:
            conn.execute(
                "INSERT OR REPLACE INTO friends (id, name, remark, ai_role, user_role, "
                "work_dir, system_prompt, avatar_path) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (fid, fname, "", ai_role, user_role, work_dir, system_prompt)
            )
            round_idx = 1
            for msg in messages:
                conn.execute(
                    "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
                    "VALUES (?, ?, ?, ?)",
                    (fid, msg["sender_type"], msg["content"], round_idx)
                )
                stats["messages"] += 1
                if msg["sender_type"] == "user":
                    round_idx += 1
            stats["friends"] += 1

    conn.commit()
    conn.close()
    return stats


# ── GUI ──

class RecoveryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ShadowTalk 数据恢复与迁移工具")
        self.root.geometry("640x520")

        self.logs_dir = find_logs_base()
        self.output_path = self.logs_dir.parent.parent / "shadowtalk.db"

        self.notebook = tk.Frame(self.root)
        self.notebook.pack(fill="x", padx=12, pady=(10, 0))

        # 模式切换按钮
        self.mode_var = tk.StringVar(value="recover")
        tk.Radiobutton(self.notebook, text="从日志恢复/导出", variable=self.mode_var,
                       value="recover", command=self._switch_mode).pack(side="left")
        tk.Radiobutton(self.notebook, text="从 TXT 导入", variable=self.mode_var,
                       value="import_txt", command=self._switch_mode).pack(side="left", padx=12)
        tk.Radiobutton(self.notebook, text="从文件夹导入", variable=self.mode_var,
                       value="import_folder", command=self._switch_mode).pack(side="left")

        # 主内容区
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill="both", expand=True)

        self._build_recover_ui()
        self._scan()

    def _switch_mode(self):
        """切换模式"""
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        mode = self.mode_var.get()
        if mode == "recover":
            self._build_recover_ui()
            self._scan()
        elif mode == "import_txt":
            self._build_import_txt_ui()
        else:
            self._build_import_folder_ui()

    def _build_recover_ui(self):
        """构建日志恢复界面"""
        # 日志目录
        tk.Label(self.main_frame, text="日志目录:", anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(self.main_frame, text=str(self.logs_dir), fg="gray", anchor="w").pack(fill="x", padx=12)

        # 好友列表
        tk.Label(self.main_frame, text="可恢复的好友（多选）:", anchor="w").pack(fill="x", padx=12, pady=(10, 0))

        list_frame = tk.Frame(self.main_frame)
        list_frame.pack(fill="both", expand=True, padx=12, pady=4)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, width=72, height=12)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 按钮
        btn_frame = tk.Frame(self.main_frame)
        btn_frame.pack(fill="x", padx=12, pady=6)
        tk.Button(btn_frame, text="全选", command=self._select_all).pack(side="left")
        tk.Button(btn_frame, text="全不选", command=self._select_none).pack(side="left", padx=4)
        tk.Button(btn_frame, text="导出到 TXT", bg="#3A7CA5", fg="white",
                  command=self._export_txt).pack(side="left", padx=(10, 0))
        tk.Button(btn_frame, text="导出到文件夹(含头像)", bg="#3A7CA5", fg="white",
                  command=self._export_folder).pack(side="left", padx=(5, 0))
        tk.Button(btn_frame, text="恢复到数据库", bg="#2E9E57", fg="white",
                  command=self._recover).pack(side="right")

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        tk.Label(self.main_frame, textvariable=self.status_var,
                 relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_import_txt_ui(self):
        """构建 TXT 导入界面"""
        tk.Label(self.main_frame, text="从 TXT 文件导入好友数据到数据库", anchor="w",
                 font=("", 11, "bold")).pack(fill="x", padx=12, pady=(15, 0))

        # TXT 文件选择
        txt_frame = tk.Frame(self.main_frame)
        txt_frame.pack(fill="x", padx=12, pady=10)
        tk.Label(txt_frame, text="TXT 文件:").pack(side="left")
        self.txt_var = tk.StringVar()
        tk.Entry(txt_frame, textvariable=self.txt_var, width=50).pack(side="left", padx=4)
        tk.Button(txt_frame, text="浏览", command=self._browse_txt).pack(side="left")

        # 输出数据库
        db_frame = tk.Frame(self.main_frame)
        db_frame.pack(fill="x", padx=12, pady=4)
        tk.Label(db_frame, text="目标数据库:").pack(side="left")
        self.import_db_var = tk.StringVar(value=str(self.output_path))
        tk.Entry(db_frame, textvariable=self.import_db_var, width=50).pack(side="left", padx=4)
        tk.Button(db_frame, text="浏览", command=self._browse_import_db).pack(side="left")

        # 导入按钮
        btn_frame = tk.Frame(self.main_frame)
        btn_frame.pack(fill="x", padx=12, pady=20)
        tk.Button(btn_frame, text="开始导入", bg="#2E9E57", fg="white",
                  font=("", 11, "bold"), command=self._import_txt).pack()

        # 状态栏
        self.status_var = tk.StringVar(value="选择 TXT 文件和目标数据库")
        tk.Label(self.main_frame, textvariable=self.status_var,
                 relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_import_folder_ui(self):
        """构建文件夹导入界面"""
        tk.Label(self.main_frame, text="从文件夹导入好友数据（含头像）", anchor="w",
                 font=("", 11, "bold")).pack(fill="x", padx=12, pady=(15, 0))

        tk.Label(self.main_frame, text="选择之前导出的文件夹，将自动导入所有好友和头像",
                 fg="gray", anchor="w").pack(fill="x", padx=12)

        # 文件夹选择
        folder_frame = tk.Frame(self.main_frame)
        folder_frame.pack(fill="x", padx=12, pady=10)
        tk.Label(folder_frame, text="导出文件夹:").pack(side="left")
        self.folder_var = tk.StringVar()
        tk.Entry(folder_frame, textvariable=self.folder_var, width=50).pack(side="left", padx=4)
        tk.Button(folder_frame, text="浏览", command=self._browse_folder).pack(side="left")

        # 目标数据库
        db_frame = tk.Frame(self.main_frame)
        db_frame.pack(fill="x", padx=12, pady=4)
        tk.Label(db_frame, text="目标数据库:").pack(side="left")
        self.import_db_var = tk.StringVar(value=str(self.output_path))
        tk.Entry(db_frame, textvariable=self.import_db_var, width=50).pack(side="left", padx=4)
        tk.Button(db_frame, text="浏览", command=self._browse_import_db).pack(side="left")

        # 导入按钮
        btn_frame = tk.Frame(self.main_frame)
        btn_frame.pack(fill="x", padx=12, pady=20)
        tk.Button(btn_frame, text="开始导入", bg="#2E9E57", fg="white",
                  font=("", 11, "bold"), command=self._import_folder).pack()

        # 状态栏
        self.status_var = tk.StringVar(value="选择导出的文件夹和目标数据库")
        tk.Label(self.main_frame, textvariable=self.status_var,
                 relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _scan(self):
        self.friends = scan_friends(self.logs_dir)
        self.listbox.delete(0, tk.END)
        for f in self.friends:
            self.listbox.insert(
                tk.END,
                f"{f['name']} (ID:{f['id']}) — {f['log_count']} 条日志, 最近: {f['last_time']}"
            )
        self.status_var.set(f"找到 {len(self.friends)} 个可恢复的好友")

    def _select_all(self):
        self.listbox.select_set(0, tk.END)

    def _select_none(self):
        self.listbox.selection_clear(0, tk.END)

    def _browse_txt(self):
        path = filedialog.askopenfilename(
            filetypes=[("TXT 文件", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.txt_var.set(path)

    def _browse_folder(self):
        path = filedialog.askdirectory(title="选择导出的文件夹")
        if path:
            self.folder_var.set(path)

    def _browse_import_db(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite DB", "*.db")],
            initialfile="shadowtalk.db")
        if path:
            self.import_db_var.set(path)

    def _export_txt(self):
        """导出选中的好友到 TXT"""
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请至少选择一个好友")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("TXT 文件", "*.txt")],
            initialfile="shadowtalk_export.txt")
        if not path:
            return

        selected = [self.friends[i] for i in sel]
        self.status_var.set("正在收集数据...")
        self.root.update()
        data = collect_friends_data(self.logs_dir, selected)
        export_friends_to_txt(data, Path(path))
        total_msgs = sum(len(d["messages"]) for d in data)
        messagebox.showinfo("导出完成",
                            f"已导出 {len(data)} 位好友\n共 {total_msgs} 条消息\n文件: {path}")
        self.status_var.set(f"导出完成: {len(data)} 位好友, {total_msgs} 条消息")

    def _export_folder(self):
        """导出选中的好友到文件夹（含头像）"""
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请至少选择一个好友")
            return

        path = filedialog.askdirectory(title="选择导出目标文件夹")
        if not path:
            return

        selected = [self.friends[i] for i in sel]
        self.status_var.set("正在收集数据...")
        self.root.update()
        data = collect_friends_data(self.logs_dir, selected)
        base_dir = self.logs_dir.parent.parent
        exported = export_friends_to_folder(self.logs_dir, data, Path(path), base_dir)
        total_msgs = sum(len(d["messages"]) for d in data)
        messagebox.showinfo("导出完成",
                            f"已导出 {len(data)} 位好友\n共 {total_msgs} 条消息\n到文件夹: {path}")
        self.status_var.set(f"导出完成: {len(data)} 位好友, {total_msgs} 条消息")

    def _recover(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请至少选择一个好友")
            return

        db_path = Path(self.output_path)
        if db_path.exists():
            if not messagebox.askyesno("确认", f"数据库已存在，是否覆盖？\n{db_path}"):
                return

        if db_path.exists():
            db_path.unlink()
        init_db(db_path)

        total = {"messages": 0, "friends": 0}
        for idx in sel:
            friend = self.friends[idx]
            self.status_var.set(f"正在恢复: {friend['name']}...")
            self.root.update()
            stats = recover_friend(self.logs_dir, friend, db_path)
            total["friends"] += 1
            total["messages"] += stats["messages"]

        messagebox.showinfo(
            "完成",
            f"已恢复 {total['friends']} 位好友\n共 {total['messages']} 条消息\n数据库: {db_path}"
        )
        self.status_var.set(f"恢复完成: {total['friends']} 位好友, {total['messages']} 条消息")

    def _import_txt(self):
        """从 TXT 导入"""
        txt_path = Path(self.txt_var.get())
        if not txt_path.exists():
            messagebox.showwarning("提示", "请选择有效的 TXT 文件")
            return

        db_path = Path(self.import_db_var.get())
        if db_path.exists():
            if not messagebox.askyesno("确认", f"数据库已存在，覆盖导入？\n{db_path}"):
                return
            db_path.unlink()

        init_db(db_path)
        self.status_var.set("正在导入...")
        self.root.update()
        stats = import_friends_from_txt(txt_path, db_path)
        messagebox.showinfo(
            "导入完成",
            f"已导入 {stats['friends']} 位好友\n共 {stats['messages']} 条消息\n数据库: {db_path}"
        )
        self.status_var.set(f"导入完成: {stats['friends']} 位好友, {stats['messages']} 条消息")

    def _import_folder(self):
        """从文件夹导入"""
        folder_path = Path(self.folder_var.get())
        if not folder_path.is_dir():
            messagebox.showwarning("提示", "请选择有效的文件夹")
            return

        db_path = Path(self.import_db_var.get())
        if db_path.exists():
            if not messagebox.askyesno("确认", f"数据库已存在，覆盖导入？\n{db_path}"):
                return
            db_path.unlink()

        init_db(db_path)
        self.status_var.set("正在导入...")
        self.root.update()
        stats = import_folders_to_db(folder_path, db_path)
        msg = f"已导入 {stats['friends']} 位好友\n共 {stats['messages']} 条消息"
        if stats["avatars"] > 0:
            msg += f"\n恢复 {stats['avatars']} 个头像"
        msg += f"\n数据库: {db_path}"
        messagebox.showinfo("导入完成", msg)
        self.status_var.set(
            f"导入完成: {stats['friends']} 位好友, {stats['messages']} 条消息, {stats['avatars']} 个头像")


def main():
    root = tk.Tk()
    app = RecoveryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
