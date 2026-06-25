"""
LLM 分层调用与资源约束 Demo

演示 harness-cook 的 LLM 分层策略、Token 追踪与成本估算、
Gate 通知推送、依赖注入容器四大核心能力。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/llm-tiering/demo_llm_tiering.py

输出:
  - Demo 1: LLM 分层调用 (ModelTier + LLMConstraints)
  - Demo 2: Token 跟踪 (TokenTracker + 成本估算 + 预算控制)
  - Demo 3: Gate 通知推送 (GateManager + 多通道 Notifier)
  - Demo 4: 依赖注入容器 (DIContainer + ServiceLocator)
"""

import sys
sys.path.insert(0, "../../packages/core")

from datetime import datetime, timezone, timedelta

# ── Demo 1 & 2: LLM 分层与 Token 跟踪 ──
from harness.llm import (
    ModelTier,
    LLMConstraints,
    TokenUsageRecord,
    TokenTracker,
    PromptTemplate,
)

# ── Demo 3: Gate 通知推送 ──
from harness.gate_notification import (
    NotificationPriority,
    DowngradeAction,
    GateApprovalDecision,
    GateNotification,
    AutoDowngrade,
    INotifier,
    LocalNotifier,
    GateApprovalRecord,
    GateManager,
)


# ═══════════════════════════════════════════════════════════════
#  Demo 1: LLM 分层调用——ModelTier + LLMConstraints
# ═══════════════════════════════════════════════════════════════

def demo_model_tier_and_constraints():
    """Demo 1: ModelTier PREMIUM/STANDARD/FAST 三级模型 + LLMConstraints 约束"""

    print("\n" + "=" * 60)
    print("Demo 1: LLM 分层调用——ModelTier + LLMConstraints")
    print("=" * 60)

    # 1.1 三级模型分层
    print("\n[1.1] ModelTier 三级模型分层:")
    for tier in ModelTier:
        print(f"  {tier.name} = {tier.value}")

    # 1.2 创建不同约束——模拟不同任务场景
    print("\n[1.2] 不同场景的 LLMConstraints 约束:")

    # 关键任务——高质量约束
    premium_constraints = LLMConstraints(
        max_tokens=8000,
        temperature=0.1,
        tier=ModelTier.PREMIUM,
        allowed_models=["claude-opus", "gpt-4"],
        degrade_on_failure=True,
    )
    print(f"  关键任务约束: {premium_constraints.summary()}")

    # 常规任务——标准约束
    standard_constraints = LLMConstraints(
        max_tokens=4000,
        temperature=0.5,
        tier=ModelTier.STANDARD,
        allowed_models=["claude-sonnet", "gpt-3.5-turbo"],
        degrade_on_failure=True,
    )
    print(f"  常规任务约束: {standard_constraints.summary()}")

    # 批量任务——快速约束
    fast_constraints = LLMConstraints(
        max_tokens=2000,
        temperature=0.8,
        tier=ModelTier.FAST,
        allowed_models=["claude-haiku", "gpt-3.5-turbo-lite"],
        blocked_models=["claude-opus"],  # 黑名单：不允许用昂贵模型
    )
    print(f"  批量任务约束: {fast_constraints.summary()}")

    # 1.3 模型验证——白名单/黑名单
    print("\n[1.3] 模型验证——白名单/黑名单:")

    test_cases = [
        (premium_constraints, "claude-opus", "关键任务用 opus"),
        (premium_constraints, "claude-haiku", "关键任务用 haiku"),
        (fast_constraints, "claude-haiku", "批量任务用 haiku"),
        (fast_constraints, "claude-opus", "批量任务用 opus(黑名单)"),
    ]
    for constraints, model, desc in test_cases:
        valid = constraints.validate_model(model)
        status = "通过" if valid else "拒绝"
        print(f"  {desc}: {model} → {status}")

    # 1.4 温度验证
    print("\n[1.4] 温度参数验证:")

    temp_cases = [
        (premium_constraints, 0.05, "关键任务低温度"),
        (premium_constraints, 0.3, "关键任务高温度(超出约束)"),
        (fast_constraints, 0.8, "批量任务高温度"),
    ]
    for constraints, temp, desc in temp_cases:
        valid = constraints.validate_temperature(temp)
        status = "合规" if valid else "超出约束"
        print(f"  {desc}: temp={temp} → {status}")

    # 1.5 PromptTemplate——按分级生成提示词
    print("\n[1.5] PromptTemplate——按分级生成提示词:")

    review_template = PromptTemplate(
        name="code-review",
        template="请对以下代码进行{review_type}审查，关注{focus_area}。",
        variables=["review_type", "focus_area"],
        tier=ModelTier.PREMIUM,
    )

    rendered = review_template.render(
        review_type="深度安全",
        focus_area="注入漏洞和数据泄露",
    )
    print(f"  模板名称: {review_template.name}")
    print(f"  建议分级: {review_template.tier.value}")
    print(f"  渲染结果: {rendered}")


# ═══════════════════════════════════════════════════════════════
#  Demo 2: Token 跟踪——TokenTracker + 成本估算 + 预算控制
# ═══════════════════════════════════════════════════════════════

def demo_token_tracker():
    """Demo 2: TokenTracker 使用记录 + 成本估算 + 预算控制"""

    print("\n" + "=" * 60)
    print("Demo 2: Token 跟踪——TokenTracker + 成本估算")
    print("=" * 60)

    tracker = TokenTracker()

    # 2.1 分级价格表
    print("\n[2.1] 分级价格表(每1K token,美元):")
    for tier, prices in TokenTracker.TIER_PRICES.items():
        print(f"  {tier.value}: input=${prices['input']}, output=${prices['output']}")

    # 2.2 模拟多次调用——不同分级
    print("\n[2.2] 模拟多次调用——记录 Token 使用:")

    # Premium: 关键代码审查
    record_p1 = TokenUsageRecord(
        model_tier=ModelTier.PREMIUM,
        model_name="claude-opus",
        input_tokens=2000,
        output_tokens=1500,
        latency_ms=3000,
    )
    tracker.record(record_p1)
    print(f"  Premium #1: input={record_p1.input_tokens}, output={record_p1.output_tokens}, "
          f"cost=${record_p1.cost_estimate:.4f}")

    # Premium: 安全审计
    record_p2 = TokenUsageRecord(
        model_tier=ModelTier.PREMIUM,
        model_name="claude-opus",
        input_tokens=5000,
        output_tokens=3000,
        latency_ms=5000,
    )
    tracker.record(record_p2)
    print(f"  Premium #2: input={record_p2.input_tokens}, output={record_p2.output_tokens}, "
          f"cost=${record_p2.cost_estimate:.4f}")

    # Standard: 常规代码生成
    record_s1 = TokenUsageRecord(
        model_tier=ModelTier.STANDARD,
        model_name="claude-sonnet",
        input_tokens=1000,
        output_tokens=800,
        latency_ms=1500,
    )
    tracker.record(record_s1)
    print(f"  Standard #1: input={record_s1.input_tokens}, output={record_s1.output_tokens}, "
          f"cost=${record_s1.cost_estimate:.4f}")

    # Standard: 单元测试生成
    record_s2 = TokenUsageRecord(
        model_tier=ModelTier.STANDARD,
        model_name="claude-sonnet",
        input_tokens=3000,
        output_tokens=2000,
        latency_ms=2500,
    )
    tracker.record(record_s2)
    print(f"  Standard #2: input={record_s2.input_tokens}, output={record_s2.output_tokens}, "
          f"cost=${record_s2.cost_estimate:.4f}")

    # Fast: 批量注释生成
    record_f1 = TokenUsageRecord(
        model_tier=ModelTier.FAST,
        model_name="claude-haiku",
        input_tokens=500,
        output_tokens=400,
        latency_ms=500,
    )
    tracker.record(record_f1)
    print(f"  Fast #1: input={record_f1.input_tokens}, output={record_f1.output_tokens}, "
          f"cost=${record_f1.cost_estimate:.4f}")

    # 2.3 使用统计概要
    print("\n[2.3] 使用统计概要:")
    summary = tracker.summary()
    print(f"  总调用次数: {summary['total_calls']}")
    print(f"  总成本: ${summary['total_cost']}")
    print(f"  分级明细:")
    for tier_name, data in summary["tier_breakdown"].items():
        print(f"    {tier_name}: calls={data['calls']}, total_tokens={data['total_tokens']}")

    # 2.4 预算控制——检查是否超出约束
    print("\n[2.4] 预算控制——Token 上限检查:")

    # 低预算约束——很快就会超限
    tight_budget = LLMConstraints(max_tokens=1000, tier=ModelTier.FAST)
    over_limit = tracker.check_over_limit(tight_budget)
    print(f"  紧预算(1000 tokens): 超限={over_limit}")

    # 高预算约束——不会超限
    generous_budget = LLMConstraints(max_tokens=50000, tier=ModelTier.PREMIUM)
    over_limit = tracker.check_over_limit(generous_budget)
    print(f"  松预算(50000 tokens): 超限={over_limit}")

    # 无约束
    over_limit = tracker.check_over_limit(None)
    print(f"  无约束: 超限={over_limit}")


# ═══════════════════════════════════════════════════════════════
#  Demo 3: Gate 通知推送——GateManager + 多通道 Notifier
# ═══════════════════════════════════════════════════════════════

class EmailNotifier:
    """邮件通知器——INotifier 实现"""

    def __init__(self):
        self._sent: list = []

    def send(self, notification: GateNotification) -> bool:
        """发送邮件通知"""
        self._sent.append(notification)
        print(f"    [邮件] 发送给 {notification.recipient}: {notification.message}")
        return True

    def receive(self, gate_id: str) -> GateApprovalDecision | None:
        """接收审批决策"""
        return None


class WebhookNotifier:
    """Webhook 通知器——INotifier 实现"""

    def __init__(self, webhook_url: str = "https://hooks.example.com/gate"):
        self._webhook_url = webhook_url
        self._sent: list = []

    def send(self, notification: GateNotification) -> bool:
        """发送 Webhook 通知"""
        self._sent.append(notification)
        payload = {
            "gate_id": notification.gate_id,
            "message": notification.message,
            "priority": notification.priority.value,
            "action_url": notification.action_url,
        }
        print(f"    [Webhook] POST {self._webhook_url}: {payload}")
        return True

    def receive(self, gate_id: str) -> GateApprovalDecision | None:
        return None


class SlackNotifier:
    """Slack 通知器——INotifier 实现"""

    def __init__(self, channel: str = "#gate-approvals"):
        self._channel = channel
        self._sent: list = []

    def send(self, notification: GateNotification) -> bool:
        """发送 Slack 通知"""
        self._sent.append(notification)
        priority_badge = {
            NotificationPriority.URGENT: ":red_circle:",
            NotificationPriority.NORMAL: ":large_blue_circle:",
            NotificationPriority.INFO: ":white_circle:",
        }
        badge = priority_badge.get(notification.priority, ":white_circle:")
        print(f"    [Slack {self._channel}] {badge} Gate {notification.gate_id}: "
              f"{notification.message}")
        return True

    def receive(self, gate_id: str) -> GateApprovalDecision | None:
        return None


class MultiChannelNotifier:
    """多通道通知器——同时推送到邮件/Webhook/Slack"""

    def __init__(self, channels: list):
        self._channels = channels

    def send(self, notification: GateNotification) -> bool:
        """同时推送到所有通道"""
        results = []
        for channel in self._channels:
            result = channel.send(notification)
            results.append(result)
        return all(results)

    def receive(self, gate_id: str) -> GateApprovalDecision | None:
        """从本地通知器接收决策"""
        for channel in self._channels:
            if isinstance(channel, LocalNotifier):
                return channel.receive(gate_id)
        return None


def demo_gate_notification():
    """Demo 3: GateManager 多通道通知推送"""

    print("\n" + "=" * 60)
    print("Demo 3: Gate 通知推送——GateManager + 多通道 Notifier")
    print("=" * 60)

    # 3.1 单通道——LocalNotifier（本地日志）
    print("\n[3.1] 单通道通知——LocalNotifier 本地日志:")
    local_notifier = LocalNotifier()
    gate_mgr_local = GateManager(notifier=local_notifier)

    notification = gate_mgr_local.create_gate(
        gate_id="gate-local-001",
        recipient="admin",
        message="代码质量检查需要审批",
        priority=NotificationPriority.NORMAL,
        deadline_minutes=30,
    )
    print(f"  通知已创建: {notification.summary()}")

    # 3.2 多通道通知——邮件/Webhook/Slack
    print("\n[3.2] 多通道通知——邮件 + Webhook + Slack:")
    email = EmailNotifier()
    webhook = WebhookNotifier(webhook_url="https://ci.example.com/gate-webhook")
    slack = SlackNotifier(channel="#ci-approvals")

    multi_notifier = MultiChannelNotifier(channels=[email, webhook, slack])
    gate_mgr_multi = GateManager(notifier=multi_notifier)

    notification = gate_mgr_multi.create_gate(
        gate_id="gate-multi-001",
        recipient="tech-lead",
        message="生产环境部署需要审批",
        priority=NotificationPriority.URGENT,
        deadline_minutes=15,
    )
    print(f"  多通道通知已推送: {notification.summary()}")

    # 3.3 多通道 + LocalNotifier（带审批决策）
    print("\n[3.3] 多通道 + LocalNotifier（可接收审批决策）:")
    email2 = EmailNotifier()
    slack2 = SlackNotifier(channel="#security-approvals")
    local2 = LocalNotifier()

    combined_notifier = MultiChannelNotifier(channels=[email2, slack2, local2])
    gate_mgr_combined = GateManager(
        notifier=combined_notifier,
        downgrade=AutoDowngrade(after_minutes=10, action=DowngradeAction.ABORT),
    )

    notification = gate_mgr_combined.create_gate(
        gate_id="gate-combined-001",
        recipient="security-team",
        message="安全漏洞修复方案需要审批",
        priority=NotificationPriority.URGENT,
        deadline_minutes=10,
    )
    print(f"  组合通知已推送: {notification.summary()}")

    # 模拟人工审批（通过 LocalNotifier 注入决策）
    local2.decide("gate-combined-001", GateApprovalDecision.APPROVED)
    decision = combined_notifier.receive("gate-combined-001")
    print(f"  审批决策: {decision.value}")

    # 3.4 通知优先级与超时检查
    print("\n[3.4] 通知优先级与超时检查:")

    priorities = [
        NotificationPriority.URGENT,
        NotificationPriority.NORMAL,
        NotificationPriority.INFO,
    ]
    for pri in priorities:
        n = GateNotification(
            gate_id=f"gate-pri-{pri.value}",
            message=f"优先级={pri.value}的测试通知",
            priority=pri,
            deadline=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        expired = n.is_expired()
        remaining = n.time_remaining()
        print(f"  {pri.value}: 已超时={expired}, 剩余秒数={remaining.total_seconds():.0f}")

    # 3.5 审批记录与统计
    print("\n[3.5] 审批记录与统计:")

    # 查看之前的审批记录
    record = gate_mgr_combined.get_record("gate-combined-001")
    if record:
        print(f"  审批记录: {record.summary()}")

    stats = gate_mgr_combined.stats()
    print(f"  统计: total_gates={stats['total_gates']}, "
          f"approved={stats['approved']}, rejected={stats['rejected']}, "
          f"timeout={stats['timeout']}, cancelled={stats['cancelled']}")

    # 3.6 降级配置
    print("\n[3.6] 自动降级配置:")
    downgrade_configs = [
        AutoDowngrade(after_minutes=30, action=DowngradeAction.SKIP,
                      fallback_message="审批超时,自动跳过继续执行"),
        AutoDowngrade(after_minutes=15, action=DowngradeAction.SIMPLIFY,
                      fallback_message="审批超时,简化审批流程"),
        AutoDowngrade(after_minutes=10, action=DowngradeAction.ABORT,
                      fallback_message="审批超时,中止执行"),
    ]
    for dg in downgrade_configs:
        deadline = dg.calculate_deadline()
        print(f"  降级策略: {dg.after_minutes}分钟后 → {dg.action.value}, "
              f"截止时间={deadline.isoformat()[:19]}")


# ═══════════════════════════════════════════════════════════════
#  Demo 4: 依赖注入容器——DIContainer + ServiceLocator
# ═══════════════════════════════════════════════════════════════

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type


class ServiceLifetime(Enum):
    """服务生命周期——3种模式"""
    SINGLETON = "singleton"   # 单例: 全局共享一个实例
    TRANSIENT = "transient"    # 瞬态: 每次请求创建新实例
    SCOPED = "scoped"          # 作用域: 同一作用域共享实例


class DIContainer:
    """依赖注入容器——服务注册/解析/生命周期管理

    功能:
    - register: 注册服务(接口类型 + 实现工厂 + 生命周期)
    - resolve: 解析服务(按类型获取实例)
    - singleton: 快捷注册单例
    - transient: 快捷注册瞬态
    - list_services: 列出所有已注册服务
    """

    def __init__(self):
        self._services: Dict[str, Dict] = {}  # service_key -> {factory, lifetime, instance}
        self._singletons: Dict[str, Any] = {}

    def register(
        self,
        service_type: type,
        factory: Callable,
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
    ) -> None:
        """注册服务

        Args:
            service_type: 服务接口/基类类型
            factory: 创建实例的工厂函数
            lifetime: 服务生命周期(单例/瞬态/作用域)
        """
        key = service_type.__name__
        self._services[key] = {
            "factory": factory,
            "lifetime": lifetime,
            "service_type": service_type,
        }
        # 单例立即创建并缓存
        if lifetime == ServiceLifetime.SINGLETON:
            self._singletons[key] = factory()

    def resolve(self, service_type: type) -> Any:
        """解析服务——获取服务实例

        Args:
            service_type: 服务接口/基类类型

        Returns:
            服务实例

        Raises:
            KeyError: 服务未注册
        """
        key = service_type.__name__
        if key not in self._services:
            raise KeyError(f"服务 '{key}' 未注册")

        service = self._services[key]
        lifetime = service["lifetime"]

        if lifetime == ServiceLifetime.SINGLETON:
            return self._singletons[key]
        elif lifetime == ServiceLifetime.TRANSIENT:
            return service["factory"]()
        elif lifetime == ServiceLifetime.SCOPED:
            # 作用域模式: 同一容器内共享（简化演示）
            if key not in self._singletons:
                self._singletons[key] = service["factory"]()
            return self._singletons[key]

    def singleton(self, service_type: type, instance: Any) -> None:
        """快捷注册单例——直接传入已创建的实例"""
        key = service_type.__name__
        self._services[key] = {
            "factory": lambda: instance,
            "lifetime": ServiceLifetime.SINGLETON,
            "service_type": service_type,
        }
        self._singletons[key] = instance

    def transient(self, service_type: type, factory: Callable) -> None:
        """快捷注册瞬态——每次解析都创建新实例"""
        self.register(service_type, factory, ServiceLifetime.TRANSIENT)

    def has_service(self, service_type: type) -> bool:
        """检查服务是否已注册"""
        return service_type.__name__ in self._services

    def list_services(self) -> List[Dict]:
        """列出所有已注册服务"""
        return [
            {
                "type": svc["service_type"].__name__,
                "lifetime": svc["lifetime"].value,
            }
            for svc in self._services.values()
        ]

    def stats(self) -> Dict:
        """容器统计"""
        return {
            "total_services": len(self._services),
            "singletons": len(self._singletons),
            "service_types": [svc["service_type"].__name__ for svc in self._services.values()],
        }


class ServiceLocator:
    """服务定位器——全局服务访问入口

    与 DIContainer 配合使用:
    - DIContainer 负责注册和依赖注入
    - ServiceLocator 提供全局访问入口

    用法:
        container = DIContainer()
        container.register(ITokenTracker, lambda: TokenTracker())
        locator = ServiceLocator(container)
        tracker = locator.get(ITokenTracker)
    """

    def __init__(self, container: Optional[DIContainer] = None):
        self._container = container or DIContainer()

    def register(self, service_type: type, factory: Callable,
                 lifetime: ServiceLifetime = ServiceLifetime.SINGLETON) -> None:
        """注册服务到容器"""
        self._container.register(service_type, factory, lifetime)

    def get(self, service_type: type) -> Any:
        """获取服务实例"""
        return self._container.resolve(service_type)

    def has(self, service_type: type) -> bool:
        """检查服务是否存在"""
        return self._container.has_service(service_type)

    def list_services(self) -> List[Dict]:
        """列出所有服务"""
        return self._container.list_services()


# ── 演示用的服务接口和实现 ──

class ITokenTracker:
    """TokenTracker 服务接口"""
    pass


class IGateManager:
    """GateManager 服务接口"""
    pass


class INotificationService:
    """通知服务接口"""
    pass


class NotificationService:
    """通知服务实现——组合多通道"""

    def __init__(self, channels: list = None):
        self._channels = channels or []

    def add_channel(self, channel: INotifier):
        self._channels.append(channel)

    def notify(self, gate_id: str, message: str, priority: NotificationPriority):
        """发送通知"""
        notification = GateNotification(
            gate_id=gate_id,
            message=message,
            priority=priority,
        )
        results = []
        for channel in self._channels:
            result = channel.send(notification)
            results.append(result)
        return all(results)


def demo_dependency_injection():
    """Demo 4: DIContainer 服务注册/定位/生命周期"""

    print("\n" + "=" * 60)
    print("Demo 4: 依赖注入容器——DIContainer + ServiceLocator")
    print("=" * 60)

    # 4.1 生命周期模式
    print("\n[4.1] ServiceLifetime 三种模式:")
    for lt in ServiceLifetime:
        desc = {
            ServiceLifetime.SINGLETON: "全局共享一个实例，适合有状态服务",
            ServiceLifetime.TRANSIENT: "每次请求创建新实例，适合无状态服务",
            ServiceLifetime.SCOPED: "同一作用域共享实例，适合请求级服务",
        }
        print(f"  {lt.name} ({lt.value}): {desc[lt]}")

    # 4.2 DIContainer——注册与解析
    print("\n[4.2] DIContainer——服务注册与解析:")

    container = DIContainer()

    # 注册单例: TokenTracker（全局共享）
    tracker_instance = TokenTracker()
    container.singleton(ITokenTracker, tracker_instance)
    print(f"  注册单例 ITokenTracker → TokenTracker")

    # 注册单例: GateManager（全局共享）
    container.register(
        IGateManager,
        lambda: GateManager(notifier=LocalNotifier()),
        ServiceLifetime.SINGLETON,
    )
    print(f"  注册单例 IGateManager → GateManager")

    # 注册瞬态: NotificationService（每次创建新实例）
    container.transient(
        INotificationService,
        lambda: NotificationService(channels=[
            EmailNotifier(),
            SlackNotifier(),
        ]),
    )
    print(f"  注册瞬态 INotificationService → NotificationService")

    # 解析服务
    tracker = container.resolve(ITokenTracker)
    print(f"  解析 ITokenTracker: {type(tracker).__name__}")

    gate_mgr = container.resolve(IGateManager)
    print(f"  解析 IGateManager: {type(gate_mgr).__name__}")

    # 4.3 单例 vs 瞬态——实例复用对比
    print("\n[4.3] 单例 vs 瞬态——实例复用对比:")

    # 单例: 多次解析返回同一实例
    tracker1 = container.resolve(ITokenTracker)
    tracker2 = container.resolve(ITokenTracker)
    same = tracker1 is tracker2
    print(f"  ITokenTracker 单例: tracker1 is tracker2 = {same}")

    # 瞬态: 多次解析返回不同实例
    ns1 = container.resolve(INotificationService)
    ns2 = container.resolve(INotificationService)
    different = ns1 is not ns2
    print(f"  INotificationService 瞬态: ns1 is not ns2 = {different}")

    # 4.4 ServiceLocator——全局访问入口
    print("\n[4.4] ServiceLocator——全局访问入口:")

    locator = ServiceLocator(container)

    tracker_via_locator = locator.get(ITokenTracker)
    print(f"  locator.get(ITokenTracker): {type(tracker_via_locator).__name__}")
    print(f"  与容器解析的实例相同: {tracker_via_locator is tracker1}")

    print(f"  locator.has(ITokenTracker): {locator.has(ITokenTracker)}")
    print(f"  locator.has(UnknownType): {locator.has(type('Unknown', (), {}))}")

    # 4.5 服务列表与统计
    print("\n[4.5] 服务列表与统计:")

    services = locator.list_services()
    for svc in services:
        print(f"  服务: {svc['type']}, 生命周期: {svc['lifetime']}")

    stats = container.stats()
    print(f"  容器统计: total_services={stats['total_services']}, "
          f"singletons={stats['singletons']}")
    print(f"  服务类型: {stats['service_types']}")

    # 4.6 依赖注入协作——TokenTracker + GateManager
    print("\n[4.6] 依赖注入协作——跨服务交互:")

    tracker = locator.get(ITokenTracker)
    gate_mgr = locator.get(IGateManager)

    # 记录 Token 使用
    record = TokenUsageRecord(
        model_tier=ModelTier.STANDARD,
        model_name="claude-sonnet",
        input_tokens=1000,
        output_tokens=500,
    )
    tracker.record(record)
    print(f"  TokenTracker 记录: {record.input_tokens}+{record.output_tokens} tokens, "
          f"cost=${record.cost_estimate:.4f}")

    # 创建 Gate 通知
    gate_mgr.create_gate(
        gate_id="gate-di-demo",
        recipient="tech-lead",
        message="依赖注入协作演示审批",
        priority=NotificationPriority.NORMAL,
    )
    print(f"  GateManager 创建: gate-di-demo")

    # 查看统计
    print(f"  TokenTracker 统计: {tracker.summary()}")
    print(f"  GateManager 统计: {gate_mgr.stats()}")

    # 4.7 错误处理——未注册服务
    print("\n[4.7] 错误处理——未注册服务:")

    class IUnknownService:
        pass

    try:
        container.resolve(IUnknownService)
    except KeyError as e:
        print(f"  解析未注册服务: KeyError → {e}")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Harness LLM Tiering & Resource Constraints Demo")
    print("=" * 60)

    demo_model_tier_and_constraints()
    demo_token_tracker()
    demo_gate_notification()
    demo_dependency_injection()

    print("\n" + "=" * 60)
    print("所有 LLM Tiering Demo 完成")
    print("=" * 60)
