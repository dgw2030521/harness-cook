"""
RollbackEngine 测试——自动回滚引擎的核心功能验证
"""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from harness.rollback import (
    RollbackSnapshot,
    SnapshotSet,
    RollbackResult,
    VerifyResult,
    RollbackEngine,
    get_rollback_engine,
    reset_rollback_engine,
)
from harness.bus import EventBus, BusEvent, BusEventType


# ─── 辅助 ────────────────────────────────────────────

@pytest.fixture
def tmp_dir():
    """创建临时目录并清理"""
    d = tempfile.mkdtemp(prefix="harness-rollback-test-")
    yield d
    # 清理
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def rollback_engine(tmp_dir):
    """创建使用临时存储目录的 RollbackEngine"""
    engine = RollbackEngine(store_dir=tmp_dir)
    yield engine


@pytest.fixture
def sample_files(tmp_dir):
    """创建示例文件用于测试"""
    files = {}
    for name, content in [("a.py", "print('hello')"), ("b.py", "x = 1")]:
        path = os.path.join(tmp_dir, name)
        with open(path, "w") as f:
            f.write(content)
        files[name] = path
    return files


# ─── RollbackSnapshot ─────────────────────────────────

class TestRollbackSnapshot:

    def test_snapshot_creation(self):
        snap = RollbackSnapshot(
            file_path="/tmp/test.py",
            content_hash=hashlib.sha256("hello".encode()).hexdigest(),
            content_snapshot="hello",
        )
        assert snap.file_path == "/tmp/test.py"
        assert snap.content_snapshot == "hello"
        assert len(snap.content_hash) == 64

    def test_snapshot_to_dict_and_from_dict(self):
        snap = RollbackSnapshot(
            file_path="/tmp/test.py",
            content_hash="abc123",
            content_snapshot="hello",
        )
        d = snap.to_dict()
        assert d["file_path"] == "/tmp/test.py"

        restored = RollbackSnapshot.from_dict(d)
        assert restored.file_path == snap.file_path
        assert restored.content_hash == snap.content_hash
        assert restored.content_snapshot == snap.content_snapshot


class TestSnapshotSet:

    def test_snapshot_set_creation(self):
        snaps = [
            RollbackSnapshot(file_path="a.py", content_hash="h1", content_snapshot="c1"),
            RollbackSnapshot(file_path="b.py", content_hash="h2", content_snapshot="c2"),
        ]
        ss = SnapshotSet(
            snapshot_id="snap-1",
            execution_id="ex-1",
            node_id="node-1",
            snapshots=snaps,
        )
        assert ss.snapshot_id == "snap-1"
        assert len(ss.snapshots) == 2

    def test_snapshot_set_serialization(self):
        snaps = [
            RollbackSnapshot(file_path="a.py", content_hash="h1", content_snapshot="c1"),
        ]
        ss = SnapshotSet(
            snapshot_id="snap-test",
            execution_id="ex-test",
            node_id="node-test",
            snapshots=snaps,
        )
        d = ss.to_dict()
        restored = SnapshotSet.from_dict(d)
        assert restored.snapshot_id == ss.snapshot_id
        assert len(restored.snapshots) == 1


# ─── RollbackEngine 核心功能 ────────────────────────────

class TestRollbackEngineCreate:

    def test_create_snapshot(self, rollback_engine, sample_files, tmp_dir):
        file_paths = [sample_files["a.py"], sample_files["b.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        assert ss.snapshot_id.startswith("snap-")
        assert len(ss.snapshots) == 2
        # 验证 hash 正确性
        for snap in ss.snapshots:
            assert len(snap.content_hash) == 64
            assert snap.content_snapshot != ""

    def test_create_snapshot_nonexistent_file(self, rollback_engine, tmp_dir):
        """不存在的文件被跳过(不记录到快照中)"""
        nonexistent = os.path.join(tmp_dir, "no_such_file.py")
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=[nonexistent],
        )
        # 不存在的文件被 skip，快照列表为空
        assert len(ss.snapshots) == 0

    def test_create_snapshot_persists_to_disk(self, rollback_engine, sample_files, tmp_dir):
        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        # 检查 JSON 文件是否存在
        json_path = Path(tmp_dir) / f"{ss.snapshot_id}.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["snapshot_id"] == ss.snapshot_id


class TestRollbackEngineRestore:

    def test_restore_snapshot(self, rollback_engine, sample_files, tmp_dir):
        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        # 修改文件
        with open(sample_files["a.py"], "w") as f:
            f.write("print('modified')")

        # 恢复
        result = rollback_engine.restore_snapshot(ss.snapshot_id)
        assert result.success
        assert result.files_restored == 1

        # 验证内容已还原
        content = Path(sample_files["a.py"]).read_text()
        assert content == "print('hello')"

    def test_restore_nonexistent_snapshot(self, rollback_engine):
        result = rollback_engine.restore_snapshot("snap-nonexistent-999")
        assert not result.success
        assert len(result.errors) > 0

    def test_restore_creates_missing_parent_dirs(self, rollback_engine, tmp_dir):
        """恢复时如果父目录不存在会自动创建"""
        deep_path = os.path.join(tmp_dir, "sub", "deep", "file.py")
        # 先创建并快照
        os.makedirs(os.path.dirname(deep_path), exist_ok=True)
        with open(deep_path, "w") as f:
            f.write("original")
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=[deep_path],
        )
        # 删除整个目录
        import shutil
        shutil.rmtree(os.path.join(tmp_dir, "sub"), ignore_errors=True)
        # 恢复
        result = rollback_engine.restore_snapshot(ss.snapshot_id)
        assert result.success
        assert Path(deep_path).read_text() == "original"


class TestRollbackEngineVerify:

    def test_verify_consistent_snapshot(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        # 不修改文件 → 验证应该一致
        result = rollback_engine.verify_snapshot(ss.snapshot_id)
        assert result.consistent
        assert result.files_consistent == 1
        assert result.files_modified == 0

    def test_verify_modified_file(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        # 修改文件
        with open(sample_files["a.py"], "w") as f:
            f.write("modified content")
        result = rollback_engine.verify_snapshot(ss.snapshot_id)
        assert not result.consistent
        assert result.files_modified == 1
        assert sample_files["a.py"] in result.modified_paths

    def test_verify_deleted_file(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        # 删除文件
        os.unlink(sample_files["a.py"])
        result = rollback_engine.verify_snapshot(ss.snapshot_id)
        assert not result.consistent
        assert result.files_missing == 1


class TestRollbackEngineList:

    def test_list_snapshots(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        rollback_engine.create_snapshot(
            execution_id="ex-2", node_id="node-2", file_paths=file_paths,
        )
        all_snaps = rollback_engine.list_snapshots()
        assert len(all_snaps) == 2

    def test_list_snapshots_filter_by_execution_id(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        rollback_engine.create_snapshot(
            execution_id="ex-2", node_id="node-2", file_paths=file_paths,
        )
        filtered = rollback_engine.list_snapshots(execution_id="ex-1")
        assert len(filtered) == 1
        assert filtered[0].execution_id == "ex-1"


class TestRollbackEngineCleanup:

    def test_cleanup_by_ttl(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        # 创建一个 "旧" 快照(手动设置 created_at)
        ss1 = rollback_engine.create_snapshot(
            execution_id="ex-old", node_id="node-1", file_paths=file_paths,
        )
        # 手动修改 JSON 使 created_at 变旧
        json_path = Path(rollback_engine._store_dir) / f"{ss1.snapshot_id}.json"
        data = json.loads(json_path.read_text())
        data["created_at"] = time.time() - 86400 * 30  # 30天前
        json_path.write_text(json.dumps(data))

        # 创建一个新快照
        rollback_engine.create_snapshot(
            execution_id="ex-new", node_id="node-2", file_paths=file_paths,
        )

        # 清理 TTL=7天的快照
        deleted = rollback_engine.cleanup_snapshots(ttl_seconds=86400 * 7)
        assert deleted == 1

    def test_cleanup_by_max_snapshots(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        for i in range(5):
            rollback_engine.create_snapshot(
                execution_id=f"ex-{i}", node_id=f"node-{i}", file_paths=file_paths,
            )
        # 只保留 2 个
        deleted = rollback_engine.cleanup_snapshots(max_snapshots=2)
        assert deleted == 3
        remaining = rollback_engine.list_snapshots()
        assert len(remaining) == 2


class TestRollbackEngineStats:

    def test_stats(self, rollback_engine, sample_files):
        file_paths = [sample_files["a.py"]]
        rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        stats = rollback_engine.stats()
        assert stats["total_snapshots"] == 1
        assert stats["total_files_snapshotted"] == 1


class TestBusEvents:

    def test_snapshot_created_event(self, rollback_engine, sample_files):
        bus = EventBus()
        events = []
        bus.subscribe(BusEventType.ROLLBACK_SNAPSHOT_CREATED, lambda e: events.append(e))
        rollback_engine._bus = bus

        file_paths = [sample_files["a.py"]]
        rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        assert len(events) == 1
        assert events[0].type == BusEventType.ROLLBACK_SNAPSHOT_CREATED

    def test_restored_event(self, rollback_engine, sample_files):
        bus = EventBus()
        events = []
        bus.subscribe(BusEventType.ROLLBACK_RESTORED, lambda e: events.append(e))
        rollback_engine._bus = bus

        file_paths = [sample_files["a.py"]]
        ss = rollback_engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=file_paths,
        )
        rollback_engine.restore_snapshot(ss.snapshot_id)
        assert len(events) == 1
        assert events[0].type == BusEventType.ROLLBACK_RESTORED


class TestConvenienceFunctions:

    def test_get_and_reset_rollback_engine(self):
        reset_rollback_engine()
        engine1 = get_rollback_engine()
        engine2 = get_rollback_engine()
        assert engine1 is engine2  # singleton
        reset_rollback_engine()
        engine3 = get_rollback_engine()
        assert engine3 is not engine1  # new instance after reset