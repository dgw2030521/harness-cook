"""
harness-cook 自动回滚引擎

RollbackEngine 是 Harness 的"安全网"——节点执行前自动创建文件快照，
节点失败时可选自动回滚到快照状态，防止部分修改破坏项目完整性。

核心能力：
  1. 创建快照: 拷贝文件列表 + 计算 SHA-256 hash
  2. 恢复快照: 还原文件内容到快照时状态
  3. 验证快照: 检查当前文件 hash 是否与快照一致
  4. 清理快照: 删除过期快照（按 TTL 或数量上限）

设计原则：
  - 快照存储在 ~/.harness/rollback/ 目录
  - 每个 ExecutionContext 有独立快照目录
  - SHA-256 确保内容完整性
  - 与 DAGEngine 紧密集成，节点执行前/后自动触发
"""

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

from harness.types import BusEvent, BusEventType, RollbackPolicy
from harness.bus import EventBus, get_bus


logger = logging.getLogger("harness.rollback")


# ─── 快照记录 ────────────────────────────────────────

@dataclass
class RollbackSnapshot:
    """
    单个文件的回滚快照——记录文件在某一时刻的内容和 hash

    Attributes:
        file_path: 原始文件的绝对路径
        content_hash: 文件内容的 SHA-256 哈希
        content_snapshot: 文件内容的完整拷贝（用于还原）
        timestamp: 快照创建时间（Unix epoch）
    """
    file_path: str
    content_hash: str
    content_snapshot: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "content_snapshot": self.content_snapshot,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RollbackSnapshot":
        """从字典反序列化"""
        return cls(
            file_path=data["file_path"],
            content_hash=data["content_hash"],
            content_snapshot=data["content_snapshot"],
            timestamp=data.get("timestamp", time.time()),
        )


# ─── 快照集 ──────────────────────────────────────────

@dataclass
class SnapshotSet:
    """
    一组文件的快照集合——一次节点执行前的完整快照

    Attributes:
        snapshot_id: 快照集唯一ID
        execution_id: 关联的执行上下文ID
        node_id: 关联的DAG节点ID
        snapshots: 文件快照列表
        created_at: 创建时间
    """
    snapshot_id: str
    execution_id: str
    node_id: str
    snapshots: List[RollbackSnapshot] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "execution_id": self.execution_id,
            "node_id": self.node_id,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotSet":
        """从字典反序列化"""
        return cls(
            snapshot_id=data["snapshot_id"],
            execution_id=data["execution_id"],
            node_id=data["node_id"],
            snapshots=[RollbackSnapshot.from_dict(s) for s in data.get("snapshots", [])],
            created_at=data.get("created_at", time.time()),
        )


# ─── 回滚结果 ────────────────────────────────────────

@dataclass
class RollbackResult:
    """回滚操作结果"""
    success: bool
    snapshot_id: str
    files_restored: int = 0
    files_failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class VerifyResult:
    """验证操作结果"""
    snapshot_id: str
    files_consistent: int = 0
    files_modified: int = 0
    files_missing: int = 0
    consistent: bool = False
    modified_paths: List[str] = field(default_factory=list)
    missing_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ─── 回滚引擎 ────────────────────────────────────────

class RollbackEngine:
    """
    自动回滚引擎——管理文件快照的创建、恢复、验证和清理

    用法:
        engine = RollbackEngine()
        # 创建快照（节点执行前）
        snapshot_set = engine.create_snapshot(
            execution_id="ex-1", node_id="node-1", file_paths=["/path/to/file.py"]
        )
        # 恢复快照（节点失败时）
        result = engine.restore_snapshot(snapshot_set.snapshot_id)
        # 验证快照完整性
        verify = engine.verify_snapshot(snapshot_set.snapshot_id)
    """

    DEFAULT_STORE_DIR = os.path.expanduser("~/.harness/rollback")
    DEFAULT_TTL_SECONDS = 86400 * 7  # 7天
    DEFAULT_MAX_SNAPSHOTS = 100

    def __init__(
        self,
        store_dir: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        bus: Optional[EventBus] = None,
    ):
        self._store_dir = Path(store_dir or self.DEFAULT_STORE_DIR)
        self._ttl_seconds = ttl_seconds
        self._max_snapshots = max_snapshots
        self._bus = bus or get_bus()
        self._snapshot_counter = 0

        # 确保存储目录存在
        self._store_dir.mkdir(parents=True, exist_ok=True)

    # ─── 创建快照 ────────────────────────────────────

    def create_snapshot(
        self,
        execution_id: str,
        node_id: str,
        file_paths: List[str],
    ) -> SnapshotSet:
        """
        创建文件快照集——拷贝文件内容 + 计算 SHA-256 hash

        Args:
            execution_id: 执行上下文ID
            node_id: DAG节点ID
            file_paths: 需要快照的文件路径列表

        Returns:
            SnapshotSet 快照集（包含所有文件的快照）
        """
        self._snapshot_counter += 1
        snapshot_id = f"snap-{self._snapshot_counter}-{int(time.time())}"

        snapshots: List[RollbackSnapshot] = []
        for file_path in file_paths:
            try:
                path = Path(file_path)
                if not path.exists():
                    logger.warning(f"File {file_path} does not exist, skipping snapshot")
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                snapshot = RollbackSnapshot(
                    file_path=file_path,
                    content_hash=content_hash,
                    content_snapshot=content,
                )
                snapshots.append(snapshot)
            except Exception as e:
                logger.error(f"Failed to snapshot {file_path}: {e}")
                # 仍然记录失败的快照（标记内容为空）
                snapshot = RollbackSnapshot(
                    file_path=file_path,
                    content_hash="",
                    content_snapshot="",
                )
                snapshots.append(snapshot)

        snapshot_set = SnapshotSet(
            snapshot_id=snapshot_id,
            execution_id=execution_id,
            node_id=node_id,
            snapshots=snapshots,
        )

        # 保存到磁盘
        self._save_snapshot_set(snapshot_set)

        # 通知事件（reserved）：快照/恢复/验证动作已同步完成并返回；当前无异步订阅者，保留作可观测/未来消费者接入
        self._bus.emit(BusEvent(
            type=BusEventType.ROLLBACK_SNAPSHOT_CREATED,
            execution_id=execution_id,
            node_id=node_id,
            data={
                "snapshot_id": snapshot_id,
                "files_count": len(snapshots),
            },
        ))

        logger.info(
            f"Created snapshot {snapshot_id} for node {node_id}: "
            f"{len(snapshots)} files snapshotted"
        )

        return snapshot_set

    # ─── 恢复快照 ────────────────────────────────────

    def restore_snapshot(self, snapshot_id: str) -> RollbackResult:
        """
        恢复快照——将所有文件还原到快照时的内容

        Args:
            snapshot_id: 快照集ID

        Returns:
            RollbackResult 恢复结果
        """
        start_time = time.time()

        snapshot_set = self._load_snapshot_set(snapshot_id)
        if not snapshot_set:
            logger.error(f"Snapshot {snapshot_id} not found")
            return RollbackResult(
                success=False,
                snapshot_id=snapshot_id,
                errors=[f"Snapshot {snapshot_id} not found"],
            )

        files_restored = 0
        files_failed = 0
        errors: List[str] = []

        for snapshot in snapshot_set.snapshots:
            try:
                if not snapshot.content_hash and not snapshot.content_snapshot:
                    # 原始文件就不存在或读取失败 → 删除当前文件（如果存在）
                    path = Path(snapshot.file_path)
                    if path.exists():
                        path.unlink()
                        logger.info(f"Removed file {snapshot.file_path} (was nonexistent in snapshot)")
                    files_restored += 1
                    continue

                path = Path(snapshot.file_path)
                # 确保父目录存在
                path.parent.mkdir(parents=True, exist_ok=True)
                # 写入快照内容
                path.write_text(snapshot.content_snapshot, encoding="utf-8")
                files_restored += 1

                logger.info(f"Restored {snapshot.file_path} from snapshot {snapshot_id}")

            except Exception as e:
                files_failed += 1
                errors.append(f"Failed to restore {snapshot.file_path}: {e}")
                logger.error(f"Failed to restore {snapshot.file_path}: {e}")

        duration_ms = int((time.time() - start_time) * 1000)

        success = files_failed == 0

        # 通知事件（reserved）：快照/恢复/验证动作已同步完成并返回；当前无异步订阅者，保留作可观测/未来消费者接入
        self._bus.emit(BusEvent(
            type=BusEventType.ROLLBACK_RESTORED if success else BusEventType.ROLLBACK_FAILED,
            execution_id=snapshot_set.execution_id,
            node_id=snapshot_set.node_id,
            data={
                "snapshot_id": snapshot_id,
                "files_restored": files_restored,
                "files_failed": files_failed,
                "duration_ms": duration_ms,
            },
        ))

        logger.info(
            f"Restored snapshot {snapshot_id}: "
            f"{files_restored} restored, {files_failed} failed, "
            f"{duration_ms}ms"
        )

        return RollbackResult(
            success=success,
            snapshot_id=snapshot_id,
            files_restored=files_restored,
            files_failed=files_failed,
            errors=errors,
            duration_ms=duration_ms,
        )

    # ─── 验证快照 ────────────────────────────────────

    def verify_snapshot(self, snapshot_id: str) -> VerifyResult:
        """
        验证快照——检查当前文件 hash 是否与快照一致

        Args:
            snapshot_id: 快照集ID

        Returns:
            VerifyResult 验证结果
        """
        snapshot_set = self._load_snapshot_set(snapshot_id)
        if not snapshot_set:
            return VerifyResult(
                snapshot_id=snapshot_id,
                consistent=False,
                errors=["Snapshot not found"],
            )

        files_consistent = 0
        files_modified = 0
        files_missing = 0
        modified_paths: List[str] = []
        missing_paths: List[str] = []

        for snapshot in snapshot_set.snapshots:
            path = Path(snapshot.file_path)

            if not snapshot.content_hash and not snapshot.content_snapshot:
                # 原始快照时文件不存在 → 当前也不应存在
                if not path.exists():
                    files_consistent += 1
                else:
                    files_modified += 1
                    modified_paths.append(snapshot.file_path)
                continue

            if not path.exists():
                files_missing += 1
                missing_paths.append(snapshot.file_path)
                continue

            try:
                current_content = path.read_text(encoding="utf-8", errors="replace")
                current_hash = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
                if current_hash == snapshot.content_hash:
                    files_consistent += 1
                else:
                    files_modified += 1
                    modified_paths.append(snapshot.file_path)
            except Exception as e:
                logger.error(f"Failed to read {snapshot.file_path} for verification: {e}")
                files_modified += 1
                modified_paths.append(snapshot.file_path)

        consistent = files_modified == 0 and files_missing == 0

        # 通知事件（reserved）：快照/恢复/验证动作已同步完成并返回；当前无异步订阅者，保留作可观测/未来消费者接入
        self._bus.emit(BusEvent(
            type=BusEventType.ROLLBACK_VERIFIED,
            execution_id=snapshot_set.execution_id,
            node_id=snapshot_set.node_id,
            data={
                "snapshot_id": snapshot_id,
                "consistent": consistent,
                "files_consistent": files_consistent,
                "files_modified": files_modified,
                "files_missing": files_missing,
            },
        ))

        return VerifyResult(
            snapshot_id=snapshot_id,
            files_consistent=files_consistent,
            files_modified=files_modified,
            files_missing=files_missing,
            consistent=consistent,
            modified_paths=modified_paths,
            missing_paths=missing_paths,
        )

    # ─── 列出快照 ────────────────────────────────────

    def list_snapshots(
        self,
        execution_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> List[SnapshotSet]:
        """
        列出快照——按执行上下文ID或节点ID过滤

        Args:
            execution_id: 可选，按执行ID过滤
            node_id: 可选，按节点ID过滤

        Returns:
            快照集列表
        """
        results: List[SnapshotSet] = []

        # 遍历存储目录中的 JSON 文件
        for json_file in self._store_dir.glob("snap-*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                snapshot_set = SnapshotSet.from_dict(data)

                if execution_id and snapshot_set.execution_id != execution_id:
                    continue
                if node_id and snapshot_set.node_id != node_id:
                    continue

                results.append(snapshot_set)
            except Exception as e:
                logger.error(f"Failed to load snapshot from {json_file}: {e}")

        # 按创建时间排序（最新在前）
        results.sort(key=lambda s: s.created_at, reverse=True)
        return results

    # ─── 清理快照 ────────────────────────────────────

    def cleanup_snapshots(
        self,
        ttl_seconds: Optional[int] = None,
        max_snapshots: Optional[int] = None,
    ) -> int:
        """
        清理过期快照——删除超过 TTL 或超过数量上限的快照

        Args:
            ttl_seconds: 过期时间（秒），None 使用默认值
            max_snapshots: 最大保留数量，None 使用默认值

        Returns:
            删除的快照数量
        """
        ttl = ttl_seconds or self._ttl_seconds
        max_snap = max_snapshots or self._max_snapshots

        all_snapshots = self.list_snapshots()
        now = time.time()
        deleted_count = 0

        # 1. 删除 TTL 过期的快照
        for snapshot_set in all_snapshots:
            age = now - snapshot_set.created_at
            if age > ttl:
                self._delete_snapshot_set(snapshot_set.snapshot_id)
                deleted_count += 1

        # 2. 如果仍超过最大数量，删除最旧的
        remaining = self.list_snapshots()
        if len(remaining) > max_snap:
            # remaining 已按时间排序（最新在前），最旧的在末尾
            to_delete = remaining[max_snap:]
            for snapshot_set in to_delete:
                self._delete_snapshot_set(snapshot_set.snapshot_id)
                deleted_count += 1

        logger.info(f"Cleanup: deleted {deleted_count} snapshots")
        return deleted_count

    # ─── 统计 ────────────────────────────────────────

    def stats(self) -> dict:
        """引擎统计"""
        all_snapshots = self.list_snapshots()
        total_files = sum(len(s.snapshots) for s in all_snapshots)
        return {
            "total_snapshots": len(all_snapshots),
            "total_files_snapshotted": total_files,
            "store_dir": str(self._store_dir),
            "ttl_seconds": self._ttl_seconds,
            "max_snapshots": self._max_snapshots,
            "snapshot_counter": self._snapshot_counter,
        }

    # ─── 内部辅助 ────────────────────────────────────

    def _save_snapshot_set(self, snapshot_set: SnapshotSet) -> None:
        """将快照集保存到磁盘"""
        filepath = self._store_dir / f"{snapshot_set.snapshot_id}.json"
        try:
            data = snapshot_set.to_dict()
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save snapshot {snapshot_set.snapshot_id}: {e}")

    def _load_snapshot_set(self, snapshot_id: str) -> Optional[SnapshotSet]:
        """从磁盘加载快照集"""
        filepath = self._store_dir / f"{snapshot_id}.json"
        if not filepath.exists():
            return None
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return SnapshotSet.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load snapshot {snapshot_id}: {e}")
            return None

    def _delete_snapshot_set(self, snapshot_id: str) -> bool:
        """从磁盘删除快照集"""
        filepath = self._store_dir / f"{snapshot_id}.json"
        if filepath.exists():
            try:
                filepath.unlink()
                return True
            except Exception as e:
                logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
                return False
        return False


# ─── 单例 ────────────────────────────────────────────

_default_engine: Optional[RollbackEngine] = None


def get_rollback_engine() -> RollbackEngine:
    """获取默认回滚引擎实例"""
    global _default_engine
    if _default_engine is None:
        _default_engine = RollbackEngine()
    return _default_engine


def reset_rollback_engine() -> None:
    """重置默认回滚引擎实例（用于测试）"""
    global _default_engine
    _default_engine = None