from shadowtalk.data.repositories import MessageRepository, FriendRepository


def extract(friend_id: int) -> list[dict]:
    messages = MessageRepository.get_unarchived(friend_id)
    # API 要求角色名为 "user" / "assistant"，数据库存的是 "user" / "ai" / "human_reply"
    # human_reply（真人回信）映射为 user，但加 [好友名] 前缀以区别于本地用户发言
    friend = FriendRepository.get_by_id(friend_id)
    author_name = friend["name"] if friend else "本人"
    result = []
    for m in messages:
        if m["sender_type"] == "ai":
            role = "assistant"
            content = m["content"]
        elif m["sender_type"] == "human_reply":
            role = "user"
            content = f"[{author_name}] {m['content']}"
        else:
            role = "user"
            content = m["content"]
        result.append({"role": role, "content": content, "layer": "L0"})
    return result
