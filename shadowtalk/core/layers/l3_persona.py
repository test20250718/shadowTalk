from shadowtalk.data.repositories import FriendRepository


def extract(friend_id: int) -> list[dict]:
    friend = FriendRepository.get_by_id(friend_id)
    if not friend:
        return []

    # 组装系统提示词，加入角色定义
    parts = []

    ai_role = friend["ai_role"] if friend["ai_role"] else ""
    user_role = friend["user_role"] if friend["user_role"] else ""

    if ai_role:
        parts.append(f"你是{ai_role}。")
    if user_role:
        parts.append(f"对方是{user_role}。")

    work_dir = friend["work_dir"] if friend["work_dir"] else ""

    if work_dir:
        parts.append(
            f"你的工作目录是 {work_dir}。需要读写文件、生成文档时，请使用该目录；目录内可自由读写。"
        )

    if friend["system_prompt"]:
        parts.append(friend["system_prompt"])

    # 告知 AI：带 [名字] 前缀的消息是自己通过邮件线下非及时回复说的，
    # 不是线上当前聊天的用户说的，避免 AI 把二者混淆
    parts.append(
        "对话中带 [名字] 前缀的消息是你通过邮件线下非及时回复说的话，"
        "不是线上的你聊天的用户说的。请区分二者，回复时请参考下。"
    )

    content = "\n".join(parts) if parts else friend["system_prompt"]

    return [{
        "role": "system",
        "content": content,
        "layer": "L3"
    }]
