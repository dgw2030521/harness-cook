"""
harness-cook IAuditStore Protocol 抽象

定义审计存储的统一契约，使 AuditStore（本地 JSON）和外部引擎存储
（Langfuse、Arize、Datadog）都能遵循同一接口。

AuditEngine.__init__ 的类型提示从 AuditStore → IAuditStore，
运行时行为不变（AuditStore 默认实例仍然是默认存储）。

设计原则：
  - Protocol 是鸭子类型契约，不需要继承
  - AuditStore 已满足所有方法签名，无需修改
  - 新的外部存储只需实现 Protocol 即可接入 AuditEngine
"""

from typing import Protocol, Optional, Dict, List, runtime_checkable

from harness.types import AuditEntry


@runtime_checkable
class IAuditStore(Protocol):
    """
    审计存储 Protocol——所有审计后端的统一契约

    方法：
      save(entry)          → 保存审计记录，返回存储标识（文件路径/trace ID 等）
      load(session_id)     → 按 session 加载审计记录
      search(query, ...)   → 搜索审计记录
      verify_chain()       → 验证哈希链完整性（外部存储可能简化实现）
      integrity_report()   → 链状态报告
    """

    def save(self, entry: AuditEntry) -> str:
        """保存审计记录 → 返回存储标识（文件路径 / trace ID 等）"""
        ...

    def load(
        self,
        session_id: str,
        date_str: Optional[str] = None,
    ) -> List[AuditEntry]:
        """按 session 加载审计记录"""
        ...

    def search(
        self,
        query: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditEntry]:
        """搜索审计记录"""
        ...

    def verify_chain(self) -> Dict:
        """验证哈希链完整性"""
        ...

    def integrity_report(self) -> Dict:
        """返回链状态报告"""
        ...

    # chain_head 是属性而非方法，Protocol 中用 @property 不强制
    # 但 AuditStore 实现了它，外部存储可选择性实现
