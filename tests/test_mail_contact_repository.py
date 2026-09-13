# tests/test_mail_contact_repository.py
# 常用联系人仓库测试：从收发邮件提取地址+名称，按频率累计
import pytest
from shadowtalk.data.repositories import MailContactRepository


def _email(addr, name="", received="2026-08-28 10:00:00", mid=None):
    """fetch worker 输出格式的邮件 dict。"""
    return {"sender_addr": addr, "sender": name,
            "received_at": received,
            "message_id": mid or f"m-{addr}-{received}-{name}"}


class TestMailContactRepository:

    def test_upsert_inserts_and_counts(self):
        """首次入库 frequency=1，新邮件（不同 message_id）累加。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "张三", mid="m1")])
        MailContactRepository.upsert_contacts([_email("a@x.com", "张三", mid="m2")])
        contacts = MailContactRepository.get_contacts()
        assert len(contacts) == 1
        assert contacts[0]["address"] == "a@x.com"
        assert contacts[0]["name"] == "张三"
        assert contacts[0]["frequency"] == 2

    def test_refresh_replay_does_not_double_count(self):
        """回归：刷新每次重放同一批邮件，frequency 不得虚增。"""
        batch = [_email("a@x.com", mid="m1"), _email("b@x.com", mid="m2")]
        MailContactRepository.upsert_contacts(batch)
        MailContactRepository.upsert_contacts(batch)  # 模拟再次刷新
        MailContactRepository.upsert_contacts(batch)  # 第三次刷新
        freqs = {c["address"]: c["frequency"]
                 for c in MailContactRepository.get_contacts()}
        assert freqs["a@x.com"] == 1
        assert freqs["b@x.com"] == 1

    def test_name_empty_keeps_old(self):
        """无显示名的邮件不抹掉已知名（部分邮件只有裸地址）。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "张三")])
        MailContactRepository.upsert_contacts([_email("a@x.com", "")])
        contacts = MailContactRepository.get_contacts()
        assert contacts[0]["name"] == "张三"

    def test_new_name_overwrites(self):
        """有新显示名时更新（用户改了昵称）。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "旧名")])
        MailContactRepository.upsert_contacts([_email("a@x.com", "新名")])
        assert MailContactRepository.get_contacts()[0]["name"] == "新名"

    def test_name_same_as_addr_treated_empty(self):
        """显示名与地址相同视为空（无意义的重复）。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "a@x.com")])
        assert MailContactRepository.get_contacts()[0]["name"] == ""

    def test_skips_invalid_addresses(self):
        """空地址 / 无 @ 的地址跳过。"""
        MailContactRepository.upsert_contacts([
            _email(""), _email("not-an-addr"), _email("ok@x.com"),
        ])
        contacts = MailContactRepository.get_contacts()
        assert len(contacts) == 1
        assert contacts[0]["address"] == "ok@x.com"

    def test_same_sender_different_emails_each_count(self):
        """同一发件人的不同邮件各计一次（真实多封 ≠ 重复拉取）。"""
        MailContactRepository.upsert_contacts([
            _email("a@x.com", mid="m1"),
            _email("a@x.com", mid="m2"),
            _email("a@x.com", mid="m3"),
        ])
        assert MailContactRepository.get_contacts()[0]["frequency"] == 3

    def test_last_seen_takes_latest(self):
        """last_seen 取最近时间。"""
        MailContactRepository.upsert_contacts(
            [_email("a@x.com", received="2026-08-20 10:00:00")])
        MailContactRepository.upsert_contacts(
            [_email("a@x.com", received="2026-08-28 09:00:00")])
        assert MailContactRepository.get_contacts()[0]["last_seen"] == "2026-08-28 09:00:00"

    def test_ordered_by_frequency(self):
        """按 frequency 降序排列（常用在前）。"""
        MailContactRepository.upsert_contacts([_email("rare@x.com", mid="r1")])
        MailContactRepository.upsert_contacts([_email("often@x.com", mid="o1")])
        MailContactRepository.upsert_contacts([_email("often@x.com", mid="o2")])
        contacts = MailContactRepository.get_contacts()
        assert contacts[0]["address"] == "often@x.com"

    def test_add_sent_contact(self):
        """发件对象进联系人；多次发送各计一次。"""
        MailContactRepository.add_sent_contact("friend@126.com")
        MailContactRepository.add_sent_contact("friend@126.com")
        contacts = MailContactRepository.get_contacts()
        assert contacts[0]["address"] == "friend@126.com"
        assert contacts[0]["frequency"] == 2

    def test_add_sent_contact_invalid(self):
        """非法地址静默跳过。"""
        MailContactRepository.add_sent_contact("")
        MailContactRepository.add_sent_contact("no-at-sign")
        assert MailContactRepository.get_contacts() == []


class TestContactMaintenance:
    """联系人维护（管理页的新建/改名/删除/搜索）。"""

    def test_add_manual_contact(self):
        """手动新建 frequency=0 的联系人。"""
        assert MailContactRepository.add_manual_contact("manual@x.com", "手动") is True
        c = MailContactRepository.get_contacts()[0]
        assert c["address"] == "manual@x.com"
        assert c["name"] == "手动"
        assert c["frequency"] == 0

    def test_add_manual_duplicate_returns_false(self):
        """地址已存在不覆盖，返回 False。"""
        MailContactRepository.add_manual_contact("a@x.com", "原名")
        assert MailContactRepository.add_manual_contact("a@x.com", "试图覆盖") is False
        assert MailContactRepository.get_contacts()[0]["name"] == "原名"

    def test_add_manual_invalid_address(self):
        """非法地址返回 False 不入库。"""
        assert MailContactRepository.add_manual_contact("bad", "x") is False
        assert MailContactRepository.add_manual_contact("", "x") is False
        assert MailContactRepository.get_contacts() == []

    def test_rename_contact(self):
        """改名不改地址，frequency 保留。"""
        MailContactRepository.upsert_contacts(
            [_email("a@x.com", "旧名", mid="m1"), _email("a@x.com", "旧名", mid="m2")])
        MailContactRepository.rename_contact("a@x.com", "新名字")
        c = MailContactRepository.get_contacts()[0]
        assert c["name"] == "新名字"
        assert c["frequency"] == 2  # 计数保留

    def test_delete_contact_clears_seen(self):
        """删除联系人连同计数标记；日后再来信从头累计。"""
        MailContactRepository.upsert_contacts(
            [_email("a@x.com", mid="m1"), _email("a@x.com", mid="m2")])
        MailContactRepository.delete_contact("a@x.com")
        assert MailContactRepository.get_contacts() == []
        # 同一封旧邮件再来（重新收同一 7 天窗口）重新计数
        MailContactRepository.upsert_contacts([_email("a@x.com", mid="m1")])
        c = MailContactRepository.get_contacts()[0]
        assert c["frequency"] == 1

    def test_search_by_name_and_address(self):
        """搜索匹配名称或地址，大小写不敏感。"""
        MailContactRepository.upsert_contacts([
            _email("zhang@x.com", "张三", mid="z1"),
            _email("lisi@x.com", "李四", mid="l1"),
        ])
        assert [c["name"] for c in MailContactRepository.search_contacts("张")] == ["张三"]
        assert [c["name"] for c in MailContactRepository.search_contacts("LISI")] == ["李四"]
        assert len(MailContactRepository.search_contacts("")) == 2  # 空关键字=全部

    def test_search_orders_by_frequency(self):
        """搜索结果按频率降序（常用的排前面）。"""
        MailContactRepository.upsert_contacts([
            _email("rare@x.com", "甲", mid="r1"),
            _email("hot@x.com", "乙", mid="h1"),
            _email("hot@x.com", "乙", mid="h2"),
        ])
        result = MailContactRepository.search_contacts("x.com")
        assert result[0]["address"] == "hot@x.com"


class TestManualName:
    """手动命名的优先级（用户起的名字不被邮件头冲掉）。"""

    def test_manual_rename_sticks_over_header(self):
        """回归：命名后新邮件头携带其他名字，显示名保持用户起的。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "旧名", mid="m1")])
        MailContactRepository.rename_contact("a@x.com", "我起的名字")
        # 后续刷新又收到该地址的邮件，头里是另一个名字
        MailContactRepository.upsert_contacts([_email("a@x.com", "邮件头名", mid="m2")])
        assert MailContactRepository.get_contacts()[0]["name"] == "我起的名字"

    def test_auto_name_still_updates_without_manual(self):
        """对照：非手动命名的联系人，名字仍随邮件头更新。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "头名一", mid="m1")])
        MailContactRepository.upsert_contacts([_email("a@x.com", "头名二", mid="m2")])
        assert MailContactRepository.get_contacts()[0]["name"] == "头名二"

    def test_manual_add_sticks_over_header(self):
        """手动新建的联系人名同样不被后续邮件头覆盖。"""
        MailContactRepository.add_manual_contact("a@x.com", "手动加的")
        MailContactRepository.upsert_contacts([_email("a@x.com", "头名", mid="m1")])
        assert MailContactRepository.get_contacts()[0]["name"] == "手动加的"

    def test_rename_to_empty_unlocks_manual(self):
        """清空名字解除手动锁：邮件头名字可重新生效。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "旧名", mid="m1")])
        MailContactRepository.rename_contact("a@x.com", "临时的")   # 手动
        MailContactRepository.rename_contact("a@x.com", "")          # 清空
        MailContactRepository.upsert_contacts([_email("a@x.com", "头名", mid="m2")])
        assert MailContactRepository.get_contacts()[0]["name"] == "头名"

    def test_get_name_map_only_named(self):
        """映射只含有名字的联系人（手动名 + 头名都算，无名排除）。"""
        MailContactRepository.upsert_contacts([
            _email("named@x.com", "张三", mid="n1"),
            _email("bare@x.com", "", mid="b1"),
        ])
        MailContactRepository.rename_contact("bare@x.com", "李四")
        name_map = MailContactRepository.get_name_map()
        assert name_map == {"named@x.com": "张三", "bare@x.com": "李四"}

    def test_get_name_map_empty_when_no_named(self):
        """全部无名时映射为空 dict（渲染层安全回退裸地址）。"""
        MailContactRepository.upsert_contacts([_email("a@x.com", "", mid="m1")])
        assert MailContactRepository.get_name_map() == {}
