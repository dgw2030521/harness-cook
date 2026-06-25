"""
AuditStore SHA-256哈希链测试

验证:
  - 哈希链创建（genesis → 逐条链接）
  - chain_head属性跟踪最新hash
  - verify_chain验证整条链完整性
  - integrity_report返回链状态报告
  - 篡改检测（修改内容后验证失败）
  - 向后兼容（无chain_hash旧记录仍可读取）
  - verify_audit_chain便利函数
"""

import json
import hashlib
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.audit import AuditStore, verify_audit_chain
from harness.types import AuditEntry


# ─── 辅助 ────────────────────────────────────────────

def _make_entry(session_id="sess1", agent_id="agent1", task="test task", ts_offset=0):
    """创建测试AuditEntry"""
    ts = datetime(2026, 6, 9, 10, 0, ts_offset)
    return AuditEntry(
        timestamp=ts,
        task=task,
        session_id=session_id,
        agent_id=agent_id,
        decisions=[{"reasoning": "auto", "action": "run", "confidence": 0.9}],
        actions=[{"tool": "shell", "input": "ls", "output": "files", "duration_ms": 100}],
        outcomes={"status": "completed"},
        risk_assessment={"level": "low"},
        escalation_history=[],
    )


def _make_legacy_json(store_dir, session_id, agent_id, timestamp, task="legacy task"):
    """手动写入无chain_hash的旧格式JSON文件"""
    date_str = timestamp.strftime("%Y%m%d")
    session_dir = Path(store_dir) / date_str / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{agent_id}_{timestamp.strftime('%H%M%S')}.json"
    filepath = session_dir / filename

    data = {
        "timestamp": timestamp.isoformat(),
        "task": task,
        "session_id": session_id,
        "agent_id": agent_id,
        "decisions": [{"reasoning": "old", "action": "run"}],
        "actions": [{"tool": "shell", "input": "echo"}],
        "outcomes": {"status": "completed"},
        "risk_assessment": None,
        "escalation_history": [],
    }
    # 注意: 没有 chain_hash 字段
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    return str(filepath)


# ─── 测试: 哈希链创建 ─────────────────────────────────

class TestChainCreation:

    def test_genesis_record_uses_genesis_hash(self, tmp_path):
        """第一条记录的previous_hash是'genesis'"""
        store = AuditStore(store_dir=str(tmp_path))
        entry = _make_entry()
        filepath = store.save(entry)

        with open(filepath) as f:
            data = json.load(f)

        # 验证chain_hash存在且是基于genesis计算的
        assert data["chain_hash"] is not None
        assert len(data["chain_hash"]) == 64  # SHA-256 hex digest length

        # 手动计算验证
        content = json.dumps({
            "timestamp": entry.timestamp.isoformat(),
            "task": entry.task,
            "session_id": entry.session_id,
            "agent_id": entry.agent_id,
            "decisions": entry.decisions,
            "actions": entry.actions,
            "outcomes": entry.outcomes,
            "risk_assessment": entry.risk_assessment,
            "escalation_history": entry.escalation_history,
        }, sort_keys=True, ensure_ascii=False)
        expected = hashlib.sha256(("genesis" + content).encode("utf-8")).hexdigest()
        assert data["chain_hash"] == expected

    def test_chain_head_tracks_latest_hash(self, tmp_path):
        """chain_head属性随每次save更新"""
        store = AuditStore(store_dir=str(tmp_path))

        # 初始: 无记录
        assert store.chain_head is None

        # 保存第一条
        e1 = _make_entry(ts_offset=0)
        store.save(e1)
        h1 = store.chain_head
        assert h1 is not None

        # 保存第二条
        e2 = _make_entry(ts_offset=1)
        store.save(e2)
        h2 = store.chain_head
        assert h2 != h1

        # 保存第三条
        e3 = _make_entry(ts_offset=2)
        store.save(e3)
        h3 = store.chain_head
        assert h3 != h2

    def test_chained_records_link_correctly(self, tmp_path):
        """后续记录的chain_hash基于前一条的hash计算"""
        store = AuditStore(store_dir=str(tmp_path))

        e1 = _make_entry(session_id="s1", ts_offset=0)
        e2 = _make_entry(session_id="s2", ts_offset=10)
        e3 = _make_entry(session_id="s3", ts_offset=20)

        f1 = store.save(e1)
        f2 = store.save(e2)
        f3 = store.save(e3)

        with open(f1) as f:
            d1 = json.load(f)
        with open(f2) as f:
            d2 = json.load(f)
        with open(f3) as f:
            d3 = json.load(f)

        # e2的hash应该基于e1的chain_hash计算
        content2 = json.dumps({
            "timestamp": e2.timestamp.isoformat(),
            "task": e2.task,
            "session_id": e2.session_id,
            "agent_id": e2.agent_id,
            "decisions": e2.decisions,
            "actions": e2.actions,
            "outcomes": e2.outcomes,
            "risk_assessment": e2.risk_assessment,
            "escalation_history": e2.escalation_history,
        }, sort_keys=True, ensure_ascii=False)
        expected_h2 = hashlib.sha256((d1["chain_hash"] + content2).encode("utf-8")).hexdigest()
        assert d2["chain_hash"] == expected_h2

        # e3的hash应该基于e2的chain_hash计算
        content3 = json.dumps({
            "timestamp": e3.timestamp.isoformat(),
            "task": e3.task,
            "session_id": e3.session_id,
            "agent_id": e3.agent_id,
            "decisions": e3.decisions,
            "actions": e3.actions,
            "outcomes": e3.outcomes,
            "risk_assessment": e3.risk_assessment,
            "escalation_history": e3.escalation_history,
        }, sort_keys=True, ensure_ascii=False)
        expected_h3 = hashlib.sha256((d2["chain_hash"] + content3).encode("utf-8")).hexdigest()
        assert d3["chain_hash"] == expected_h3


# ─── 测试: 链验证 ─────────────────────────────────────

class TestChainVerification:

    def test_verify_valid_chain(self, tmp_path):
        """验证完整无损的链 → valid=True"""
        store = AuditStore(store_dir=str(tmp_path))

        for i in range(5):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i)
            store.save(entry)

        result = store.verify_chain()
        assert result["valid"] is True
        assert result["total_records"] == 5
        assert result["verified_records"] == 5
        assert result["legacy_records"] == 0
        assert len(result["tampered"]) == 0

    def test_verify_empty_store(self, tmp_path):
        """空存储 → valid=True, total_records=0"""
        store = AuditStore(store_dir=str(tmp_path))
        result = store.verify_chain()
        assert result["valid"] is True
        assert result["total_records"] == 0

    def test_detect_tampered_content(self, tmp_path):
        """篡改记录内容 → verify_chain检测到hash不匹配"""
        store = AuditStore(store_dir=str(tmp_path))

        e1 = _make_entry(session_id="s1", ts_offset=0)
        e2 = _make_entry(session_id="s2", ts_offset=10)
        e3 = _make_entry(session_id="s3", ts_offset=20)

        f1 = store.save(e1)
        f2 = store.save(e2)
        f3 = store.save(e3)

        # 篡改第二条记录的task内容
        with open(f2) as f:
            data = json.load(f)
        data["task"] = "TAMPERED TASK"  # 修改内容但不改chain_hash
        with open(f2, "w") as f:
            json.dump(data, f, indent=2)

        # 重新扫描并验证
        store2 = AuditStore(store_dir=str(tmp_path))
        result = store2.verify_chain()

        assert result["valid"] is False
        assert len(result["tampered"]) >= 1
        # 被篡改的应该是第二条记录（index=1）
        tampered = result["tampered"][0]
        assert tampered["index"] == 1
        assert "hash mismatch" in tampered["description"]

    def test_detect_tampered_hash(self, tmp_path):
        """篡改chain_hash本身 → verify_chain检测到hash不匹配"""
        store = AuditStore(store_dir=str(tmp_path))

        e1 = _make_entry(session_id="s1", ts_offset=0)
        e2 = _make_entry(session_id="s2", ts_offset=10)

        f1 = store.save(e1)
        f2 = store.save(e2)

        # 篡改第二条记录的chain_hash
        with open(f2) as f:
            data = json.load(f)
        data["chain_hash"] = "fake_hash_value_00000000000000000000000000000000000000000000000000000000000000"
        with open(f2, "w") as f:
            json.dump(data, f, indent=2)

        store2 = AuditStore(store_dir=str(tmp_path))
        result = store2.verify_chain()

        assert result["valid"] is False
        assert len(result["tampered"]) >= 1

    def test_cascading_detection(self, tmp_path):
        """篡改中间记录 → 后续记录也可能检测为异常（因为prev_hash变了）"""
        store = AuditStore(store_dir=str(tmp_path))

        files = []
        for i in range(4):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i*10)
            files.append(store.save(entry))

        # 篡改第2条记录（index=1）的内容
        with open(files[1]) as f:
            data = json.load(f)
        data["task"] = "TAMPERED"
        with open(files[1], "w") as f:
            json.dump(data, f, indent=2)

        store2 = AuditStore(store_dir=str(tmp_path))
        result = store2.verify_chain()

        assert result["valid"] is False
        # 至少第2条记录会被检测为被篡改
        tampered_indices = [t["index"] for t in result["tampered"]]
        assert 1 in tampered_indices


# ─── 测试: 向后兼容 ───────────────────────────────────

class TestBackwardCompatibility:

    def test_load_legacy_records(self, tmp_path):
        """无chain_hash的旧记录仍可load"""
        store_dir = str(tmp_path)

        # 写入一条旧格式记录
        ts = datetime(2026, 6, 9, 9, 0, 0)
        _make_legacy_json(store_dir, "sess_old", "agent_old", ts)

        store = AuditStore(store_dir=store_dir)
        entries = store.load("sess_old", "20260609")

        assert len(entries) == 1
        entry = entries[0]
        assert entry.task == "legacy task"
        assert entry.chain_hash is None  # 旧记录无chain_hash

    def test_mixed_legacy_and_new(self, tmp_path):
        """混合旧记录和新记录: 旧记录跳过验证，新记录正常验证"""
        store_dir = str(tmp_path)

        # 写入旧格式记录
        ts_legacy = datetime(2026, 6, 9, 9, 0, 0)
        _make_legacy_json(store_dir, "sess_old", "agent_old", ts_legacy)

        # 写入新格式记录
        store = AuditStore(store_dir=store_dir)
        e_new = _make_entry(session_id="s_new", ts_offset=30)
        store.save(e_new)

        # verify_chain
        result = store.verify_chain()
        assert result["valid"] is True
        assert result["legacy_records"] == 1
        assert result["verified_records"] == 1
        assert result["total_records"] == 2

    def test_search_legacy_records(self, tmp_path):
        """search方法也能读取旧记录"""
        store_dir = str(tmp_path)

        ts = datetime(2026, 6, 9, 9, 30, 0)
        _make_legacy_json(store_dir, "sess_old", "agent_old", ts, task="legacy search task")

        store = AuditStore(store_dir=store_dir)
        results = store.search("legacy search")
        assert len(results) == 1
        assert results[0].chain_hash is None

    def test_chain_head_rebuilt_from_existing(self, tmp_path):
        """从已有记录重建chain_head"""
        store_dir = str(tmp_path)

        # 写入3条新格式记录
        store1 = AuditStore(store_dir=store_dir)
        for i in range(3):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i*5)
            store1.save(entry)

        head1 = store1.chain_head

        # 新建一个AuditStore实例，应该能从文件重建chain_head
        store2 = AuditStore(store_dir=store_dir)
        assert store2.chain_head == head1

        # 继续追加记录，链接应该正确
        e4 = _make_entry(session_id="s4", ts_offset=15)
        f4 = store2.save(e4)

        result = store2.verify_chain()
        assert result["valid"] is True
        assert result["total_records"] == 4


# ─── 测试: integrity_report ──────────────────────────

class TestIntegrityReport:

    def test_empty_report(self, tmp_path):
        """空存储 → status='empty'"""
        store = AuditStore(store_dir=str(tmp_path))
        report = store.integrity_report()

        assert report["status"] == "empty"
        assert report["total_records"] == 0
        assert report["chain_head"] is None
        assert "No audit records" in report["recommendation"]

    def test_valid_report(self, tmp_path):
        """完整链 → status='valid'"""
        store = AuditStore(store_dir=str(tmp_path))
        for i in range(3):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i)
            store.save(entry)

        report = store.integrity_report()
        assert report["status"] == "valid"
        assert report["total_records"] == 3
        assert report["verified_records"] == 3
        assert report["tampered_count"] == 0
        assert "integrity verified" in report["recommendation"]

    def test_compromised_report(self, tmp_path):
        """篡改链 → status='compromised'"""
        store = AuditStore(store_dir=str(tmp_path))

        files = []
        for i in range(3):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i*10)
            files.append(store.save(entry))

        # 篡改第一条记录
        with open(files[0]) as f:
            data = json.load(f)
        data["task"] = "HACKED"
        with open(files[0], "w") as f:
            json.dump(data, f, indent=2)

        store2 = AuditStore(store_dir=str(tmp_path))
        report = store2.integrity_report()

        assert report["status"] == "compromised"
        assert report["tampered_count"] >= 1
        assert "compromised" in report["recommendation"]

    def test_mixed_report(self, tmp_path):
        """混合旧记录和新记录 → status='mixed'"""
        store_dir = str(tmp_path)

        ts_legacy = datetime(2026, 6, 9, 8, 0, 0)
        _make_legacy_json(store_dir, "sess_old", "agent_old", ts_legacy)

        store = AuditStore(store_dir=store_dir)
        e_new = _make_entry(session_id="s_new", ts_offset=0)
        store.save(e_new)

        report = store.integrity_report()
        assert report["status"] == "mixed"
        assert report["legacy_records"] == 1
        assert report["verified_records"] == 1


# ─── 测试: verify_audit_chain便利函数 ─────────────────

class TestConvenienceFunction:

    def test_verify_audit_chain_valid(self, tmp_path):
        """便利函数验证完整链"""
        store = AuditStore(store_dir=str(tmp_path))
        for i in range(3):
            entry = _make_entry(session_id=f"s{i}", ts_offset=i)
            store.save(entry)

        result = verify_audit_chain(store_dir=str(tmp_path))
        assert result["valid"] is True
        assert result["total_records"] == 3

    def test_verify_audit_chain_tampered(self, tmp_path):
        """便利函数检测篡改"""
        store = AuditStore(store_dir=str(tmp_path))
        e1 = _make_entry(session_id="s1", ts_offset=0)
        e2 = _make_entry(session_id="s2", ts_offset=10)
        f1 = store.save(e1)
        f2 = store.save(e2)

        # 篡改
        with open(f1) as f:
            data = json.load(f)
        data["task"] = "TAMPERED"
        with open(f1, "w") as f:
            json.dump(data, f, indent=2)

        result = verify_audit_chain(store_dir=str(tmp_path))
        assert result["valid"] is False