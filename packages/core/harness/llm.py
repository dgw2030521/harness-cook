"""
Agent 资源约束层——约束 Agent 的资源使用边界

harness-cook 对接的是 Agent 平台（Claude Code/Hermes），不直接调 LLM。
Agent 平台自己管 LLM 调度、熔断、路由，harness 只需约束行为边界。

保留的核心能力：
- ModelTier: 模型分级建议（premium/standard/fast）
- LLMConstraints: Agent 资源约束定义（token预算、温度限制、模型白黑名单）
- TokenUsageRecord/TokenTracker: Token 消耗追踪与成本估算
- PromptTemplate: 提示词模板管理

已移除（定位偏移，不应由harness直接调度）：
- ILLMProvider/LLMDispatcher/CircuitBreaker/ModelRouter — LLM调度是Agent平台职责
- LLMCallRequest/LLMCallResult — 直接调用LLM的请求/响应模型
- BackoffConfig/CircuitState — 退避策略和熔断状态，Agent平台内部处理
- LLMErrorType — LLM错误分类，Agent平台内部处理
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import logging

logger = logging.getLogger("harness.llm")


# ═══════════════════════════════════════════════════════════
#  模型分级——Agent 行为约束的建议分级
# ═══════════════════════════════════════════════════════════

class ModelTier(Enum):
    """模型分级——给 Agent 平台的约束建议

    harness 不直接调度 LLM，但可以建议 Agent 平台使用哪个分级。
    最终决策权在 Agent 平台。
    """
    PREMIUM = "premium"    # 高质量: 适合关键任务
    STANDARD = "standard"  # 常规: 适合大多数任务
    FAST = "fast"          # 快速: 适合简单/批量任务


# ═══════════════════════════════════════════════════════════
#  Agent 资源约束——约束 Agent 的资源使用边界
# ═══════════════════════════════════════════════════════════

@dataclass
class LLMConstraints:
    """Agent 资源约束——限制 Agent 的资源使用

    harness 不直接调 LLM，但需要约束 Agent 的行为边界：
    - token 预算（防止 Agent 无限制消耗 token）
    - 温度参数（约束 Agent 的随机性）
    - 模型白黑名单（约束 Agent 可以使用哪些模型）
    """
    max_tokens: Optional[int] = None           # 单次调用 token 上限
    max_context_tokens: Optional[int] = None    # 总上下文 token 上限
    temperature: Optional[float] = None         # 温度参数约束(范围0.0-1.0)
    tier: ModelTier = ModelTier.STANDARD        # 建议使用的模型分级
    allowed_models: Optional[List[str]] = None  # 白名单: 只允许这些模型
    blocked_models: Optional[List[str]] = None  # 黑名单: 不允许这些模型
    max_retries: int = 3                        # 最大重试次数
    timeout: int = 120                          # 单次调用超时(秒)
    degrade_on_failure: bool = True             # 失败时是否建议降级

    def validate_model(self, model_name: str) -> bool:
        """验证模型是否在约束允许范围内"""
        if self.allowed_models and model_name not in self.allowed_models:
            return False
        if self.blocked_models and model_name in self.blocked_models:
            return False
        return True

    def validate_temperature(self, temp: float) -> bool:
        """验证温度参数是否在约束范围内"""
        if self.temperature is not None:
            return 0.0 <= temp <= self.temperature
        return 0.0 <= temp <= 1.0

    def summary(self) -> str:
        """约束概要"""
        parts = []
        if self.max_tokens:
            parts.append(f"Token上限={self.max_tokens}")
        if self.temperature is not None:
            parts.append(f"温度≤{self.temperature}")
        parts.append(f"建议分级={self.tier.value}")
        if self.allowed_models:
            parts.append(f"白名单={len(self.allowed_models)}个")
        if self.blocked_models:
            parts.append(f"黑名单={len(self.blocked_models)}个")
        if self.degrade_on_failure:
            parts.append("失败降级=开启")
        return " | ".join(parts) if parts else "无约束"


# ═══════════════════════════════════════════════════════════
#  Token 使用追踪——Agent 资源消耗的审计与统计
# ═══════════════════════════════════════════════════════════

@dataclass
class TokenUsageRecord:
    """单次调用 token 使用记录"""
    model_tier: ModelTier
    model_name: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_estimate: float = 0.0           # 成本估算(美元)
    latency_ms: int = 0                   # 调用延迟
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.timestamp is None:
            from datetime import datetime
            self.timestamp = datetime.now().isoformat()


class TokenTracker:
    """Token 使用追踪器——聚合+统计+成本估算

    追踪 Agent 的 token 消耗，用于审计和预算控制。
    不直接调度 LLM，只记录 Agent 平台报告的 token 使用数据。
    """

    # 分级价格(每1K token,美元)——可配置
    TIER_PRICES: Dict[ModelTier, Dict[str, float]] = {
        ModelTier.PREMIUM: {"input": 0.03, "output": 0.06},
        ModelTier.STANDARD: {"input": 0.005, "output": 0.015},
        ModelTier.FAST: {"input": 0.001, "output": 0.002},
    }

    def __init__(self):
        self._records: List[TokenUsageRecord] = []
        self._tier_totals: Dict[ModelTier, Dict[str, int]] = {
            tier: {"input": 0, "output": 0, "total": 0, "calls": 0}
            for tier in ModelTier
        }
        self._total_cost: float = 0.0

    def record(self, usage: TokenUsageRecord) -> None:
        """记录一次调用"""
        self._records.append(usage)
        self._tier_totals[usage.model_tier]["input"] += usage.input_tokens
        self._tier_totals[usage.model_tier]["output"] += usage.output_tokens
        self._tier_totals[usage.model_tier]["total"] += usage.total_tokens
        self._tier_totals[usage.model_tier]["calls"] += 1

        # 成本估算
        prices = self.TIER_PRICES.get(usage.model_tier)
        if prices:
            cost = (
                usage.input_tokens / 1000 * prices["input"] +
                usage.output_tokens / 1000 * prices["output"]
            )
            usage.cost_estimate = cost
            self._total_cost += cost

    def check_over_limit(self, constraints: Optional[LLMConstraints] = None) -> bool:
        """检查是否超出约束token上限"""
        if not constraints or not constraints.max_tokens:
            return False
        total = sum(t["total"] for t in self._tier_totals.values())
        return total > constraints.max_tokens

    def summary(self) -> Dict[str, Any]:
        """使用统计概要"""
        return {
            "total_cost": round(self._total_cost, 4),
            "total_calls": len(self._records),
            "tier_breakdown": {
                tier.value: {
                    "calls": data["calls"],
                    "total_tokens": data["total"],
                }
                for tier, data in self._tier_totals.items()
                if data["calls"] > 0
            },
        }


# ═══════════════════════════════════════════════════════════
#  Prompt 模板——提示词参数化管理
# ═══════════════════════════════════════════════════════════

@dataclass
class PromptTemplate:
    """提示词模板——参数化生成系统提示词"""
    name: str
    template: str              # 模板文本,用 {variable} 引用变量
    variables: List[str] = field(default_factory=list)  # 模板变量名
    tier: ModelTier = ModelTier.STANDARD  # 建议使用的分级

    def render(self, **kwargs) -> str:
        """渲染模板——替换变量"""
        result = self.template
        for var in self.variables:
            value = kwargs.get(var, "")
            result = result.replace(f"{{{var}}}", str(value))
        return result


# ═══════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════

_global_tracker: Optional[TokenTracker] = None


def get_tracker() -> TokenTracker:
    """获取全局Token追踪器"""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenTracker()
    return _global_tracker
