"""
Agent 行为约束——从 nextX AgentConstraint 提取的设计蓝图

约束是 Harness 对 Agent 的行为边界控制：
- Agent 可以做什么（file_patterns 限定操作范围）
- Agent 不能做什么（no_destructive 防止危险操作）
- Agent 做多少（max_changes 防止过度修改）

nextX 的 AgentConstraint 是：
  { filePattern, maxChanges, requireReview, noDestructive }

harness-cook 在此基础上扩展：
- timeout: 单任务执行超时（防止Agent无限循环）
- priority: Agent优先级（调度器参考）
- allowed_commands: 允许执行的终端命令白名单
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class AgentPriority(Enum):
    """Agent 优先级——调度器在高并发时按优先级排序"""
    LOW = "low"         # 后台辅助任务
    NORMAL = "normal"   # 常规任务
    HIGH = "high"       # 重要任务（如安全扫描）
    CRITICAL = "critical"  # 关键路径任务（如生产部署验证）


class ConstraintSeverity(Enum):
    """约束违规严重度——影响Agent行为检查的处理策略"""
    WARNING = "warning"     # 警告：记录但不阻断
    BLOCKING = "blocking"   # 阻断：阻止Agent继续执行
    CRITICAL = "critical"   # 严重：阻断+触发升级


class ConstraintType(Enum):
    """约束类型——标识触发的是哪类约束"""
    FILE_PATTERN = "file_pattern"
    MAX_CHANGES = "max_changes"
    DESTRUCTIVE = "destructive"
    COMMAND = "command"
    TIMEOUT = "timeout"
    TOKENS = "tokens"


@dataclass
class AgentConstraints:
    """Agent 行为约束——Harness 管控 Agent 的行为边界
    
    设计来源：nextX AgentConstraint + harness-cook 扩展
    nextX 定义: { filePattern, maxChanges, requireReview, noDestructive }
    harness-cook 增加: timeout, priority, allowed_commands, max_tokens
    
    用法:
        constraints = AgentConstraints(
            file_patterns=["*.py", "*.ts"],
            max_changes=50,
            require_review=True,
            no_destructive=True,
            timeout=300,  # 5分钟超时
            priority=AgentPriority.HIGH,
            allowed_commands=["pytest", "git status", "npm test"],
            max_tokens=4000
        )
    """
    # ── nextX 原有约束 ──
    file_patterns: List[str] = field(default_factory=list)
    """允许操作的文件模式列表（空=不限）。例: ["*.py", "src/**/*.ts"]"""
    
    max_changes: Optional[int] = None
    """单次执行最大变更文件数。None=不限。防止Agent一次性改太多文件"""
    
    require_review: bool = False
    """是否必须经过人工审查才能提交。高危操作时开启"""
    
    no_destructive: bool = False
    """禁止破坏性操作（删除文件、force push、drop table等）"""
    
    # ── harness-cook 扩展约束 ──
    timeout: Optional[int] = None
    """单任务执行超时（秒）。None=不限。防止Agent无限循环"""
    
    priority: AgentPriority = AgentPriority.NORMAL
    """Agent优先级。调度器在高并发时按此排序"""
    
    allowed_commands: List[str] = field(default_factory=list)
    """允许执行的终端命令白名单（空=不限）。例: ["pytest", "git status"]"""
    
    max_tokens: Optional[int] = None
    """单次执行最大Token消耗。None=不限。防止Token预算超标"""
    
    description: str = ""
    """约束的人类可读描述——用于审计日志"""

    def validate_file_access(self, file_path: str) -> bool:
        """验证Agent是否有权限操作该文件
        
        Returns:
            True = 允许操作
            False = 约束禁止
        
        空file_patterns表示不限 → 任何文件都允许
        """
        if not self.file_patterns:
            return True  # 无限制
        
        import fnmatch
        for pattern in self.file_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

    def validate_command(self, command: str) -> bool:
        """验证Agent是否有权限执行该终端命令
        
        Returns:
            True = 允许执行
            False = 约束禁止
        
        空allowed_commands表示不限 → 任何命令都允许
        """
        if not self.allowed_commands:
            return True  # 无限制
        
        # 提取命令的基础名称（去掉参数）
        base_cmd = command.strip().split()[0] if command.strip() else ""
        for allowed in self.allowed_commands:
            # 允许 "pytest" 匹配 "pytest -v tests/"
            allowed_base = allowed.strip().split()[0]
            if base_cmd == allowed_base:
                return True
        return False

    def is_destructive_blocked(self) -> bool:
        """是否禁止破坏性操作"""
        return self.no_destructive

    def needs_review(self) -> bool:
        """是否需要人工审查"""
        return self.require_review

    def summary(self) -> str:
        """约束摘要——用于审计日志和显示"""
        parts = []
        if self.file_patterns:
            parts.append(f"文件限制: {', '.join(self.file_patterns)}")
        if self.max_changes:
            parts.append(f"最多变更: {self.max_changes}个文件")
        if self.require_review:
            parts.append("必须审查")
        if self.no_destructive:
            parts.append("禁破坏性操作")
        if self.timeout:
            parts.append(f"超时: {self.timeout}s")
        if self.max_tokens:
            parts.append(f"Token上限: {self.max_tokens}")
        if self.allowed_commands:
            parts.append(f"命令白名单: {len(self.allowed_commands)}项")
        return " | ".join(parts) if parts else "无约束"


@dataclass
class ConstraintViolation:
    """约束违规记录——Agent突破行为边界时记录"""
    agent_id: str
    constraint_type: ConstraintType   # 枚举化，不再用裸字符串
    detail: str             # 具体违规描述
    severity: ConstraintSeverity = ConstraintSeverity.WARNING  # 枚举化，不再用裸字符串
    timestamp: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            from datetime import datetime
            self.timestamp = datetime.now().isoformat()