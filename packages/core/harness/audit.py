"""
harness-cook 审计溯源与可观测

Audit 是 Harness 的"黑匣子"——记录每次任务的完整决策链：
  做了什么、为什么做、结果怎样、风险如何、是否升级。
所有 Agent 的每一个决策都留下审计痕迹，事后可追溯、可复盘、可问责。

SHA-256哈希链保证审计记录不可篡改：每条记录的chain_hash由
前一条的hash与当前内容拼接后计算SHA-256得到。genesis记录
使用"genesis"作为previous_hash。
"""

import hashlib
import logging
import time
import json
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from harness.types import AuditEntry, AuditStats, TaskResult
from harness.bus import EventBus, BusEventType, BusEvent, get_bus
from harness.config import find_project_root
from harness.integrations.audit_store_protocol import IAuditStore


logger = logging.getLogger("harness.audit")


# ─── 审计存储 ────────────────────────────────────────

class AuditStore:
    """
    审计存储——持久化审计记录（SHA-256哈希链保证不可篡改）

    默认使用 JSON 文件存储（简单可靠）。
    可以替换为数据库存储（SQLite/PostgreSQL）。

    哈希链机制:
      - 每条记录写入时计算 chain_hash = SHA-256(prev_hash + content)
      - genesis记录的 prev_hash = "genesis"
      - chain_head 属性记录最新hash，作为下一条记录的前置hash
      - verify_chain 方法验证整条链完整性
      - 向后兼容: 无 chain_hash 的旧记录仍可读取（跳过链验证）
    """

    GENESIS_HASH = "genesis"

    def __init__(
        self,
        store_dir: Optional[str] = None,
        project_dir: Optional[str] = None,
    ):
        """
        初始化审计存储

        存储路径策略（审计数据跟随项目）：
          1. 显式指定 store_dir → 使用指定路径
          2. 指定 project_dir → 使用 project_dir/.harness/audit/
          3. 自动检测项目根目录 → 使用 {root}/.harness/audit/
          4. 以上都没有 → 使用 ~/.harness/audit/（降级）

        Args:
            store_dir: 显式指定存储目录（最高优先级）
            project_dir: 项目目录，审计写入该项目的 .harness/audit/
        """
        if store_dir:
            resolved = Path(store_dir)
        elif project_dir:
            resolved = Path(project_dir) / ".harness" / "audit"
        else:
            root = find_project_root()
            resolved = root / ".harness" / "audit"
            # 降级：如果项目根就是 cwd 且不是 git 仓库，用用户目录
            if root == Path.cwd().resolve() and not (root / ".git").exists():
                resolved = Path("~/.harness/audit").expanduser()

        self._store_dir = resolved
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._chain_head: Optional[str] = None
        self._scan_chain_head()
        # 内存搜索索引：lazy build
        self._index_built: bool = False
        self._index: Dict[str, list[dict]] = {}  # agent_id → [{filepath, task, timestamp, session_id}]

    # ─── 哈希链核心 ────────────────────────────────────

    def _compute_hash(self, previous_hash: str, content: str) -> str:
        """计算SHA-256(previous_hash + content)"""
        raw = previous_hash + content
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _entry_content_json(self, entry: AuditEntry) -> str:
        """提取entry的核心内容用于哈希计算（不含chain_hash自身）"""
        return json.dumps({
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

    def _scan_chain_head(self) -> None:
        """扫描所有已有记录，重建chain_head（最新hash）"""
        all_records = self._collect_all_records()
        if not all_records:
            self._chain_head = None
            return

        # 找到最后一条有chain_hash的记录
        last_hashed = None
        for filepath, data in all_records:
            if "chain_hash" in data and data["chain_hash"]:
                last_hashed = data["chain_hash"]

        self._chain_head = last_hashed

    @property
    def chain_head(self) -> Optional[str]:
        """返回当前哈希链的最新hash（下一条记录的前置hash）"""
        return self._chain_head

    # ─── 持久化 ─────────────────────────────────────────

    def save(self, entry: AuditEntry) -> str:
        """保存审计记录 → 计算chain_hash → 写入JSON → 返回文件路径"""
        date_str = entry.timestamp.strftime("%Y%m%d")
        session_dir = self._store_dir / date_str / entry.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # 计算哈希链
        content_json = self._entry_content_json(entry)
        previous_hash = self._chain_head or self.GENESIS_HASH
        chain_hash = self._compute_hash(previous_hash, content_json)

        # 写入entry的chain_hash
        entry.chain_hash = chain_hash

        filename = f"{entry.agent_id}_{entry.timestamp.strftime('%H%M%S')}.json"
        filepath = session_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": entry.timestamp.isoformat(),
                "task": entry.task,
                "session_id": entry.session_id,
                "agent_id": entry.agent_id,
                "decisions": entry.decisions,
                "actions": entry.actions,
                "outcomes": entry.outcomes,
                "risk_assessment": entry.risk_assessment,
                "escalation_history": entry.escalation_history,
                "chain_hash": chain_hash,
            }, f, indent=2, ensure_ascii=False)

        # 更新chain_head
        self._chain_head = chain_hash

        # 增量更新搜索索引
        self._update_index(entry, str(filepath))

        return str(filepath)

    def load(self, session_id: str, date_str: Optional[str] = None) -> list[AuditEntry]:
        """加载审计记录（向后兼容: 无chain_hash的旧记录仍可读取）"""
        if not date_str:
            date_str = datetime.now().strftime("%Y%m%d")

        session_dir = self._store_dir / date_str / session_id
        if not session_dir.exists():
            return []

        entries = []
        for filepath in sorted(session_dir.glob("*.json")):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                entries.append(AuditEntry(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    task=data["task"],
                    session_id=data["session_id"],
                    agent_id=data["agent_id"],
                    decisions=data["decisions"],
                    actions=data["actions"],
                    outcomes=data["outcomes"],
                    risk_assessment=data.get("risk_assessment"),
                    escalation_history=data.get("escalation_history", []),
                    chain_hash=data.get("chain_hash"),  # 向后兼容
                ))
        return entries

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """搜索审计记录（使用内存索引加速，lazy build）

        索引策略：
          - 首次搜索时构建索引（遍历所有 JSON 文件，提取 agent_id/task/timestamp/session_id）
          - 后续搜索走索引，只读取匹配的文件
          - 新增记录时增量更新索引
        """
        # 确保索引已构建
        if not self._index_built:
            self._build_index()

        # 通过索引过滤
        candidates: list[str] = []  # 文件路径列表

        if agent_id:
            # 按 agent_id 精确匹配
            for rec in self._index.get(agent_id, []):
                candidates.append(rec["filepath"])
        else:
            # 全量候选
            for recs in self._index.values():
                for rec in recs:
                    candidates.append(rec["filepath"])

        # 关键词过滤（通过索引中的 task 字段预过滤）
        if query:
            query_lower = query.lower()
            if agent_id:
                # 已通过 agent_id 缩小范围，在索引中预过滤
                filtered = []
                for rec in self._index.get(agent_id, []):
                    if query_lower in rec.get("task", "").lower():
                        filtered.append(rec["filepath"])
                candidates = filtered
            else:
                # 全量预过滤
                filtered = []
                for recs in self._index.values():
                    for rec in recs:
                        if query_lower in rec.get("task", "").lower():
                            filtered.append(rec["filepath"])
                candidates = filtered

        # 按时间倒序
        candidates.sort(reverse=True)

        # 读取匹配文件，构建 AuditEntry
        results = []
        for filepath_str in candidates:
            if len(results) >= limit:
                break

            try:
                with open(filepath_str, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append(AuditEntry(
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        task=data["task"],
                        session_id=data["session_id"],
                        agent_id=data["agent_id"],
                        decisions=data["decisions"],
                        actions=data["actions"],
                        outcomes=data["outcomes"],
                        risk_assessment=data.get("risk_assessment"),
                        escalation_history=data.get("escalation_history", []),
                        chain_hash=data.get("chain_hash"),
                    ))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed audit file {filepath_str}: {e}")
                continue
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid audit data in {filepath_str}: {e}")
                continue

        return results

    # ─── 内存索引 ────────────────────────────────────────

    def _build_index(self) -> None:
        """构建内存搜索索引（lazy，首次搜索时调用）"""
        self._index.clear()

        for filepath in sorted(self._store_dir.rglob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                aid = data.get("agent_id", "unknown")
                if aid not in self._index:
                    self._index[aid] = []
                self._index[aid].append({
                    "filepath": str(filepath),
                    "task": data.get("task", ""),
                    "timestamp": data.get("timestamp", ""),
                    "session_id": data.get("session_id", ""),
                })
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed audit file {filepath}: {e}")
                continue
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid audit data in {filepath}: {e}")
                continue

        self._index_built = True
        logger.debug(f"Audit index built: {sum(len(v) for v in self._index.values())} records across {len(self._index)} agents")

    def _update_index(self, entry: AuditEntry, filepath: str) -> None:
        """增量更新索引（新增记录时调用）"""
        if not self._index_built:
            return  # 索引未构建，无需更新，下次搜索时会全量构建

        aid = entry.agent_id
        if aid not in self._index:
            self._index[aid] = []
        self._index[aid].append({
            "filepath": filepath,
            "task": entry.task,
            "timestamp": entry.timestamp.isoformat(),
            "session_id": entry.session_id,
        })

    # ─── 链验证 ─────────────────────────────────────────

    def _collect_all_records(self) -> List[Tuple[Path, dict]]:
        """收集所有审计记录文件及其内容，按时间排序"""
        records = []
        for filepath in sorted(self._store_dir.rglob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                records.append((filepath, data))
            except json.JSONDecodeError as e:
                # 损坏文件 = 链断裂，必须记录而非跳过
                logger.warning(f"Corrupted audit file {filepath} (chain break): {e}")
                records.append((filepath, {"_corrupted": True, "_error": str(e), "_filepath": str(filepath)}))
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid audit data in {filepath}: {e}")
                records.append((filepath, {"_corrupted": True, "_error": str(e), "_filepath": str(filepath)}))
        # 按timestamp排序确保链序正确（损坏记录排在末尾）
        valid_records = [r for r in records if not r[1].get("_corrupted")]
        corrupted_records = [r for r in records if r[1].get("_corrupted")]
        valid_records.sort(key=lambda r: r[1].get("timestamp", ""))
        return valid_records + corrupted_records

    def verify_chain(self) -> Dict:
        """
        验证整条哈希链完整性

        返回:
          {
            "valid": bool,            # 整条链是否完整无篡改
            "total_records": int,     # 总记录数
            "verified_records": int,  # 有chain_hash的记录数
            "legacy_records": int,    # 无chain_hash的旧记录数
            "tampered": [             # 被篡改的记录详情
              {
                "filepath": str,
                "index": int,
                "expected_hash": str,
                "actual_hash": str,
                "description": str,
              }
            ],
            "broken_links": [         # 链断裂位置
              {
                "filepath": str,
                "index": int,
                "description": str,
              }
            ],
          }
        """
        records = self._collect_all_records()
        result = {
            "valid": True,
            "total_records": len(records),
            "verified_records": 0,
            "legacy_records": 0,
            "tampered": [],
            "broken_links": [],
        }

        if not records:
            return result

        # 分离legacy记录和hash记录，构建验证序列
        prev_hash = self.GENESIS_HASH

        for i, (filepath, data) in enumerate(records):
            # 损坏文件标记为链断裂
            if data.get("_corrupted"):
                result["valid"] = False
                result["broken_links"].append({
                    "filepath": str(filepath),
                    "index": i,
                    "description": f"Record #{i} ({filepath.name}): file corrupted, cannot verify chain link",
                })
                continue

            if "chain_hash" not in data or not data["chain_hash"]:
                # 旧记录无chain_hash，跳过验证但记录
                result["legacy_records"] += 1
                continue

            result["verified_records"] += 1
            actual_hash = data["chain_hash"]

            # 重建expected hash: SHA-256(prev_hash + content_without_chain_hash)
            content_for_hash = json.dumps({
                "timestamp": data["timestamp"],
                "task": data["task"],
                "session_id": data["session_id"],
                "agent_id": data["agent_id"],
                "decisions": data["decisions"],
                "actions": data["actions"],
                "outcomes": data["outcomes"],
                "risk_assessment": data.get("risk_assessment"),
                "escalation_history": data.get("escalation_history", []),
            }, sort_keys=True, ensure_ascii=False)
            expected_hash = self._compute_hash(prev_hash, content_for_hash)

            if actual_hash != expected_hash:
                result["valid"] = False
                result["tampered"].append({
                    "filepath": str(filepath),
                    "index": i,
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                    "description": f"Record #{i} ({filepath.name}): hash mismatch, content may be tampered",
                })

            # 下一条记录的前置hash = 当前记录的chain_hash（即使被篡改也用actual以检测后续断裂）
            prev_hash = actual_hash

        return result

    def integrity_report(self) -> Dict:
        """
        返回链状态报告（比verify_chain更丰富的摘要）

        返回:
          {
            "status": "valid" | "compromised" | "empty" | "mixed",
            "chain_head": str | None,
            "total_records": int,
            "verified_records": int,
            "legacy_records": int,
            "tampered_count": int,
            "broken_links_count": int,
            "tampered_details": [...],
            "broken_links_details": [...],
            "recommendation": str,
          }
        """
        verification = self.verify_chain()

        if verification["total_records"] == 0:
            status = "empty"
        elif verification["tampered"] or verification["broken_links"]:
            status = "compromised"
        elif verification["legacy_records"] > 0 and verification["verified_records"] > 0:
            status = "mixed"
        elif verification["legacy_records"] > 0:
            status = "legacy_only"
        else:
            status = "valid"

        recommendations = {
            "empty": "No audit records found. Start recording audit entries to build the chain.",
            "valid": "Audit chain integrity verified. All records are intact and properly linked.",
            "compromised": f"Chain integrity compromised! {len(verification['tampered'])} tampered records detected. Investigate immediately.",
            "mixed": "Chain partially verified. Legacy records exist without chain_hash; new records are properly linked.",
            "legacy_only": "All records are legacy (no chain_hash). Consider re-saving records to add chain protection.",
        }

        return {
            "status": status,
            "chain_head": self._chain_head,
            "total_records": verification["total_records"],
            "verified_records": verification["verified_records"],
            "legacy_records": verification["legacy_records"],
            "tampered_count": len(verification["tampered"]),
            "broken_links_count": len(verification["broken_links"]),
            "tampered_details": verification["tampered"],
            "broken_links_details": verification["broken_links"],
            "recommendation": recommendations[status],
        }


# ─── 便利函数 ────────────────────────────────────────

def verify_audit_chain(store_dir: str = "~/.harness/audit") -> Dict:
    """
    便利函数: 验证审计哈希链完整性

    用法:
        from harness import verify_audit_chain
        result = verify_audit_chain()
        if result["valid"]:
            print("审计链完整性验证通过")
        else:
            print("发现篡改:", result["tampered"])

    参数:
        store_dir: 审计存储目录路径

    返回:
        与 AuditStore.verify_chain() 相同的字典
    """
    store = AuditStore(store_dir)
    return store.verify_chain()


# ─── 审计引擎 ────────────────────────────────────────

class AuditEngine:
    """
    审计引擎——记录决策、生成审计日志、计算统计数据

    用法:
        engine = AuditEngine()
        engine.record_decision(session_id, agent_id, task, reasoning, action)
        engine.record_action(session_id, agent_id, tool, input, output)
        stats = engine.get_stats()
    """

    def __init__(
        self,
        store: Optional[IAuditStore] = None,
        bus: Optional[EventBus] = None,
    ):
        self._store = store or AuditStore()
        self._bus = bus or get_bus()
        self._current_session_entries: Dict[str, AuditEntry] = {}
        self._stats = AuditStats()

        # 订阅Bus事件，自动记录
        self._bus.subscribe(BusEventType.NODE_START, self._on_node_start)
        self._bus.subscribe(BusEventType.NODE_COMPLETE, self._on_node_complete)
        self._bus.subscribe(BusEventType.NODE_FAIL, self._on_node_fail)
        self._bus.subscribe(BusEventType.ESCALATION, self._on_escalation)

    def record_decision(
        self,
        session_id: str,
        agent_id: str,
        task: str,
        reasoning: str,
        action: str,
        confidence: float = 1.0,
    ) -> None:
        """记录一个决策"""
        key = f"{session_id}:{agent_id}"
        if key not in self._current_session_entries:
            self._current_session_entries[key] = AuditEntry(
                timestamp=datetime.now(),
                task=task,
                session_id=session_id,
                agent_id=agent_id,
                decisions=[],
                actions=[],
                outcomes={},
            )

        entry = self._current_session_entries[key]
        entry.decisions.append({
            "reasoning": reasoning,
            "action": action,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
        })

    def record_action(
        self,
        session_id: str,
        agent_id: str,
        tool: str,
        input_summary: str,
        output_summary: str,
        duration_ms: int = 0,
    ) -> None:
        """记录一个行动"""
        key = f"{session_id}:{agent_id}"
        if key not in self._current_session_entries:
            self._current_session_entries[key] = AuditEntry(
                timestamp=datetime.now(),
                task="",
                session_id=session_id,
                agent_id=agent_id,
                decisions=[],
                actions=[],
                outcomes={},
            )

        entry = self._current_session_entries[key]
        entry.actions.append({
            "tool": tool,
            "input": input_summary,
            "output": output_summary,
            "duration_ms": duration_ms,
        })

    def finalize_entry(self, session_id: str, agent_id: str, outcomes: dict) -> str:
        """完成审计记录 → 保存到存储"""
        key = f"{session_id}:{agent_id}"
        entry = self._current_session_entries.get(key)
        if not entry:
            return ""

        entry.outcomes = outcomes
        filepath = self._store.save(entry)

        # 更新统计
        self._stats.total_tasks += 1
        if outcomes.get("status") == "completed":
            self._stats.delivered += 1
        elif outcomes.get("status") == "escalated":
            self._stats.escalated += 1
        elif outcomes.get("auto_fixed"):
            self._stats.auto_fixed += 1

        # 清除当前会话记录
        del self._current_session_entries[key]

        return filepath

    def get_stats(self) -> AuditStats:
        """获取审计统计"""
        if self._stats.total_tasks > 0:
            self._stats.verification_pass_rate = (
                self._stats.delivered / self._stats.total_tasks
            )
        return self._stats

    def search(self, query: str, **kwargs) -> list[AuditEntry]:
        """搜索审计记录"""
        return self._store.search(query, **kwargs)

    # ─── Bus事件回调 ─────────────────────────────────

    def _on_node_start(self, event: BusEvent) -> None:
        """节点开始 → 初始化审计记录"""
        if event.data:
            self.record_decision(
                session_id=event.execution_id,
                agent_id=event.data.get("agent_type", "unknown"),
                task=event.data.get("task", ""),
                reasoning="Node started by DAG engine",
                action="start",
            )

    def _on_node_complete(self, event: BusEvent) -> None:
        """节点完成 → 更新统计"""
        self._stats.delivered += 1

    def _on_node_fail(self, event: BusEvent) -> None:
        """节点失败 → 记录失败"""
        if event.data:
            self.record_decision(
                session_id=event.execution_id,
                agent_id="unknown",
                task="",
                reasoning=f"Node failed: {event.data.get('reason', 'unknown')}",
                action="fail",
                confidence=0.0,
            )

    def _on_escalation(self, event: BusEvent) -> None:
        """升级人工 → 记录升级"""
        self._stats.escalated += 1