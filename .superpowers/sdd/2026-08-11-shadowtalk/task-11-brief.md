# Task 11: Friend Service

**Files:**
- Create: `shadowtalk/core/friend_service.py`
- Create: `tests/test_friend_service.py`

## Interfaces
- Consumes: `FriendRepository`, `MessageRepository`, `SummaryRepository`, `Database`
- Produces:
  - `FriendService.create(name, remark, system_prompt, avatar_path) -> int`
  - `FriendService.delete(friend_id, keep_messages=False) -> None`
  - `FriendService.update_avatar(friend_id, new_path) -> None`

## Implementation

```python
# shadowtalk/core/friend_service.py
import shutil
import os
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)
from shadowtalk.data.database import Database


class FriendService:
    AVATAR_DIR = "data/avatars"

    @staticmethod
    def create(name: str, remark: str, system_prompt: str,
               avatar_source_path: str = "") -> int:
        avatar_path = ""
        if avatar_source_path and os.path.exists(avatar_source_path):
            os.makedirs(FriendService.AVATAR_DIR, exist_ok=True)
            temp_dir = f"{FriendService.AVATAR_DIR}/temp"
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = f"{temp_dir}/{os.path.basename(avatar_source_path)}"
            shutil.copy2(avatar_source_path, temp_path)
            avatar_path = temp_path

        friend_id = FriendRepository.insert(name, remark, system_prompt, avatar_path)

        if avatar_path:
            ext = os.path.splitext(avatar_path)[1]
            final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
            final_path = f"{final_dir}/avatar{ext}"
            os.makedirs(final_dir, exist_ok=True)
            shutil.move(avatar_path, final_path)
            FriendRepository.update(friend_id, avatar_path=final_path)

        temp_dir = f"{FriendService.AVATAR_DIR}/temp"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        return friend_id

    @staticmethod
    def delete(friend_id: int, keep_messages: bool = False):
        if not keep_messages:
            with Database.transaction() as conn:
                conn.execute("DELETE FROM chat_messages WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM batch_summary WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM high_level_summary WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM friends WHERE id=?", (friend_id,))
        else:
            FriendRepository.delete(friend_id)

        avatar_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
        if os.path.exists(avatar_dir):
            shutil.rmtree(avatar_dir, ignore_errors=True)

    @staticmethod
    def update_avatar(friend_id: int, new_avatar_path: str):
        friend = FriendRepository.get_by_id(friend_id)
        if not friend:
            return
        old_path = friend["avatar_path"]
        ext = os.path.splitext(new_avatar_path)[1]
        final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
        final_path = f"{final_dir}/avatar{ext}"
        os.makedirs(final_dir, exist_ok=True)
        shutil.copy2(new_avatar_path, final_path)
        FriendRepository.update(friend_id, avatar_path=final_path)
        if old_path and os.path.exists(old_path):
            os.remove(old_path)
```

## Tests

```python
# tests/test_friend_service.py
import os
import tempfile
from shadowtalk.core.friend_service import FriendService
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def test_create_friend():
    fid = FriendService.create("测试", "备注", "人设", "")
    friend = FriendRepository.get_by_id(fid)
    assert friend["name"] == "测试"
    assert friend["remark"] == "备注"

def test_create_with_avatar():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake_image_data")
        avatar_path = f.name
    
    try:
        fid = FriendService.create("有头像", "", "", avatar_path)
        friend = FriendRepository.get_by_id(fid)
        assert friend["avatar_path"] != ""
        assert os.path.exists(friend["avatar_path"])
    finally:
        os.unlink(avatar_path)

def test_delete_with_cascade():
    fid = FriendService.create("待删除", "", "", "")
    MessageRepository.insert(fid, "user", "消息", 1)
    
    FriendService.delete(fid, keep_messages=False)
    assert FriendRepository.get_by_id(fid) is None
    msgs = MessageRepository.get_unarchived(fid)
    assert len(msgs) == 0
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement friend_service.py
4. Run to verify PASS
5. Commit
