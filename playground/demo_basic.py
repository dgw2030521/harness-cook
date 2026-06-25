#!/usr/bin/env python3
"""
harness-cook 基础使用 Demo

本demo展示 harness-cook SDK 的核心功能：
  1. 注册 Agent（通过 @harness_agent 装饰器 + 手动注册）
  2. 创建 DAG 工作流（3节点: 分析→编码→验证）
  3. 用 DAGEngine 执行工作流
  4. ComplianceEngine 合规扫描
  5. Guardrails PII 检测与脱敏

运行方式:
  python playground/demo_basic.py

无需任何外部依赖，纯 Python 3.9+ 可运行。
"""

import sys
import os
import time
import json

# ── 设置 sys.path，确保能找到 harness 包 ──────────────────────────
# playground/demo_basic.py → 项目根目录/packages/core/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "packages", "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

# ── 导入 harness 核心模块 ──────────────────────────────────────────
from harness import __version__
from harness.types import (
    AgentCapability, AgentType, AgentDefinition,
    TaskResult, Artifact,
    DAGNode, DAGEdge, DAGWorkflow,
    GateMode, GateDefinition, GateCheck, CheckResult,
    ComplianceCategory, ComplianceRule,
    GuardrailAction, InputGuardrailConfig, OutputGuardrailConfig,
    ExecutionTrace, TraceNode,
)
from harness.registry import AgentRegistry
from harness.engine import DAGEngine, ExecutionContext
from harness.compliance import ComplianceEngine, RulePack, security_rule_pack, privacy_rule_pack
from harness.guardrails import InputGuardrails, OutputGuardrails, PIIDetector, GuardrailsPair, default_guardrails
from harness.decorators import harness_agent
from harness.constraints import AgentConstraints, AgentPriority
from harness.bus import EventBus, BusEventType, BusEvent
from harness.knowledge import (
    KnowledgeType, KnowledgeScope, KnowledgeEntry, KnowledgeQuery,
    LocalKnowledgeProvider,
)
from harness.learning import (
    LearningEngine, ExperienceStore, AntiPatternDetector, PatternMiner,
)


# ═══════════════════════════════════════════════════════════════════
#  辅助函数：格式化打印
# ═══════════════════════════════════════════════════════════════════

def print_header(title: str) -> None:
    """打印分节标题"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_sub(title: str) -> None:
    """打印子标题"""
    print()
    print(f"── {title} ──")


def print_result(label: str, value: any) -> None:
    """打印单行结果"""
    if isinstance(value, dict) or isinstance(value, list):
        print(f"  {label}:")
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"  {label}: {value}")


# ═══════════════════════════════════════════════════════════════════
#  Step 1: 注册 Agent
# ═══════════════════════════════════════════════════════════════════

print_header("Step 1: 注册 Agent")

# 创建独立的 EventBus 和 AgentRegistry（避免全局单例冲突）
bus = EventBus()
registry = AgentRegistry(bus=bus)

# ── 方式A: 用 @harness_agent 装饰器注册（自动注册到全局 Registry）──
# 注意：装饰器使用全局 Registry，这里仅展示用法，不用于后续执行
print_sub("方式A: @harness_agent 装饰器")

@harness_agent(
    name="需求分析师-decorator",
    capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
    constraints=AgentConstraints(
        priority=AgentPriority.HIGH,
        max_changes=5,
        no_destructive=True,
    ),
    gate_mode=GateMode.HYBRID,
    toolsets=["terminal"],
    agent_type=AgentType.ANALYST,
)
def analyze_decorator(task: str, context: dict) -> TaskResult:
    """需求分析Agent（装饰器版本）"""
    return TaskResult(
        task_id=context.get("task_id", "t-analyze-001"),
        agent_id="analyze_decorator",
        status="completed",
        artifacts=[
            Artifact(
                type="doc",
                path="analysis_report.md",
                content="# 需求分析报告\n\n## 核心需求\n- 实现用户登录功能\n- 支持多因素认证\n\n## 影响范围\n- auth 模块\n- session 模块",
            ),
        ],
        duration_ms=200,
        tokens_used=300,
    )

print_result("装饰器注册", "Agent '需求分析师-decorator' 已自动注册到全局Registry")

# ── 方式B: 手动创建 AgentDefinition + 实现，注册到独立 Registry ──
print_sub("方式B: 手动注册（定义+实现分离）")


# 实现 IExecutableAgent protocol 的类
class AnalystAgent:
    """分析师 Agent —— 解析需求，产出分析报告"""

    def execute(self, task: str, context: dict) -> TaskResult:
        return TaskResult(
            task_id=context.get("task_id", "t-analyze-001"),
            agent_id="analyst",
            status="completed",
            artifacts=[
                Artifact(
                    type="doc",
                    path="analysis_report.md",
                    content="# 需求分析报告\n\n## 核心需求\n- 实现用户登录功能\n- 支持多因素认证\n\n## 影响范围\n- auth 模块\n- session 模块",
                ),
            ],
            duration_ms=200,
            tokens_used=300,
        )

    def estimate_tokens(self, task: str) -> int:
        return len(task) * 4 + 500


class CoderAgent:
    """编码者 Agent —— 根据需求实现代码"""

    def execute(self, task: str, context: dict) -> TaskResult:
        # 模拟：从上游分析报告生成代码
        code_content = '''def login(username, password):
    """用户登录函数"""
    if authenticate(username, password):
        session = create_session(username)
        return session
    return None
'''
        return TaskResult(
            task_id=context.get("task_id", "t-code-001"),
            agent_id="coder",
            status="completed",
            artifacts=[
                Artifact(
                    type="code",
                    path="auth/login.py",
                    content=code_content,
                ),
            ],
            duration_ms=500,
            tokens_used=800,
        )

    def estimate_tokens(self, task: str) -> int:
        return len(task) * 6 + 800


class ValidatorAgent:
    """验证者 Agent —— 检查代码是否合规"""

    def execute(self, task: str, context: dict) -> TaskResult:
        # 模拟：验证代码安全性
        validation_content = "# 验证报告\n\n## 检查项\n- ✅ 函数签名正确\n- ✅ 无硬编码密钥\n- ✅ 无SQL注入风险\n\n## 结论\n代码质量合格，可以发布。"
        return TaskResult(
            task_id=context.get("task_id", "t-validate-001"),
            agent_id="validator",
            status="completed",
            artifacts=[
                Artifact(
                    type="doc",
                    path="validation_report.md",
                    content=validation_content,
                ),
            ],
            duration_ms=150,
            tokens_used=200,
        )

    def estimate_tokens(self, task: str) -> int:
        return len(task) * 3 + 200


# 创建 AgentDefinition
analyst_def = AgentDefinition(
    id="analyst",
    name="需求分析师",
    capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
    toolsets=["terminal", "file"],
    agent_type=AgentType.ANALYST,
    system_prompt="你是一个专业的需求分析师，擅长解析需求并评估影响范围。",
)

coder_def = AgentDefinition(
    id="coder",
    name="编码者",
    capabilities=[AgentCapability.EXECUTE, AgentCapability.REASON],
    toolsets=["terminal", "file", "code"],
    agent_type=AgentType.CODER,
    system_prompt="你是一个专业的编码者，擅长根据需求实现高质量代码。",
)

validator_def = AgentDefinition(
    id="validator",
    name="验证者",
    capabilities=[AgentCapability.PERCEIVE, AgentCapability.REASON],
    toolsets=["terminal", "file"],
    agent_type=AgentType.VALIDATOR,
    system_prompt="你是一个专业的验证者，擅长检查代码安全性和合规性。",
)

# 注册到 Registry
registry.register(analyst_def, AnalystAgent())
registry.register(coder_def, CoderAgent())
registry.register(validator_def, ValidatorAgent())

# 打印注册结果
stats = registry.stats()
print_result("已注册 Agent 数", stats["total_agents"])
print_result("已就绪 Agent 数", stats["ready_agents"])
print_result("Agent列表", [
    {"id": r.id, "name": r.definition.name, "type": r.definition.agent_type.value if r.definition.agent_type else "N/A"}
    for r in registry.list_all()
])


# ═══════════════════════════════════════════════════════════════════
#  Step 2: 创建 DAG 工作流（分析→编码→验证）
# ═══════════════════════════════════════════════════════════════════

print_header("Step 2: 创建 DAG 工作流")

# 创建 3 个 DAGNode
node_analyze = DAGNode(
    id="analyze",
    agent_type="analyst",          # 引用 Registry 中的 Agent ID
    task="分析用户登录功能需求，评估影响范围",
    inputs=[],                     # 入口节点，无上游输入
    outputs=["code"],              # 输出给 coding 节点
)

node_code = DAGNode(
    id="code",
    agent_type="coder",
    task="根据分析报告实现用户登录代码",
    inputs=[],                      # 依赖关系由 DAGEdge 声明，不在 inputs 中重复
    outputs=[],                     # outputs 仅用于标注，拓扑排序依赖 edges
)

node_verify = DAGNode(
    id="verify",
    agent_type="validator",
    task="验证登录代码的安全性和合规性",
    inputs=[],                      # 依赖关系由 DAGEdge 声明
    outputs=[],                     # 终止节点
)

# 创建 2 条 DAGEdge
edge_1 = DAGEdge(from_node="analyze", to_node="code")
edge_2 = DAGEdge(from_node="code", to_node="verify")

# 组装完整工作流
workflow = DAGWorkflow(
    id="wf-login-feature",
    name="用户登录功能开发",
    description="从需求分析到代码实现再到验证的完整开发流程",
    nodes=[node_analyze, node_code, node_verify],
    edges=[edge_1, edge_2],
    entry_node="analyze",
    exit_nodes=["verify"],
)

print_result("工作流ID", workflow.id)
print_result("工作流名称", workflow.name)
print_result("节点数", len(workflow.nodes))
print_result("边数", len(workflow.edges))
print_result("节点列表", [
    {"id": n.id, "agent_type": n.agent_type, "task": n.task}
    for n in workflow.nodes
])
print_result("边列表", [
    {"from": e.from_node, "to": e.to_node, "condition": e.condition or "无"}
    for e in workflow.edges
])


# ═══════════════════════════════════════════════════════════════════
#  Step 3: 用 DAGEngine 执行工作流
# ═══════════════════════════════════════════════════════════════════

print_header("Step 3: DAGEngine 执行工作流")

# 创建 DAGEngine（使用独立的 Registry 和 EventBus）
engine = DAGEngine(registry=registry, bus=bus)

# 先查看拓扑排序（计划阶段）
print_sub("拓扑排序（执行计划）")
execution_order = engine.plan(workflow)
print_result("执行顺序", execution_order)

# 执行工作流
print_sub("执行工作流")
context = engine.execute(workflow)

print_result("执行ID", context.execution_id)
print_result("工作流ID", context.workflow_id)
print_result("执行耗时(ms)", context.duration_ms)
print_result("节点状态", context.node_status)
print_result("完成节点", list(context.completed_nodes))
print_result("失败节点", list(context.failed_nodes))
print_result("是否升级人工", context.escalated)

# 打印每个节点的产出物摘要
print_sub("各节点产出物")
for node_id, artifacts in context.node_artifacts.items():
    print(f"  [{node_id}] 产出物:")
    for art in artifacts:
        print(f"    - type={art.type}, path={art.path}")
        # 只打印前100字符的内容摘要
        preview = art.content[:100].replace("\n", " ")
        print(f"    - content(前100字): {preview}...")


# ═══════════════════════════════════════════════════════════════════
#  Step 4: ComplianceEngine 合规扫描
# ═══════════════════════════════════════════════════════════════════

print_header("Step 4: ComplianceEngine 合规扫描")

# 创建合规引擎
compliance_engine = ComplianceEngine(bus=bus)

# 加载安全规则包和隐私规则包
compliance_engine.load_pack(security_rule_pack())
compliance_engine.load_pack(privacy_rule_pack())

print_result("已加载规则包", compliance_engine.list_packs())
print_result("规则包统计", compliance_engine.stats())

# ── 扫描产出物 ────────────────────────────────────────────
print_sub("扫描工作流产出物")
all_artifacts = []
for node_id, artifacts in context.node_artifacts.items():
    all_artifacts.extend(artifacts)

results = compliance_engine.scan(all_artifacts)

passed = sum(1 for r in results if r.passed)
failed = sum(1 for r in results if not r.passed)
print_result("扫描结果", f"共 {len(results)} 条规则检查, 通过 {passed}, 违规 {failed}")

if failed > 0:
    print_sub("违规详情")
    for r in results:
        if not r.passed:
            print(f"  ❌ 规则: {r.rule_id}")
            print(f"     严重性: {r.severity}")
            print(f"     发现: {r.findings}")
            print(f"     修复建议: {r.remediation}")

# ── 快速扫描一段含有硬编码密钥的代码 ──────────────────────
print_sub("快速扫描：硬编码密钥检测")
unsafe_code = '''
API_KEY = "sk-abc123def456ghi789jkl012mno345pqr678"
password = "super_secret_password_123"
user_email = "admin@company.com"
'''

quick_results = compliance_engine.scan_quick(unsafe_code, "config.py")
passed_q = sum(1 for r in quick_results if r.passed)
failed_q = sum(1 for r in quick_results if not r.passed)
print_result("快速扫描结果", f"共 {len(quick_results)} 条, 通过 {passed_q}, 违规 {failed_q}")

if failed_q > 0:
    print("  违规列表:")
    for r in quick_results:
        if not r.passed:
            print(f"    ❌ {r.rule_id} ({r.severity}): {r.findings}")
            if r.remediation:
                print(f"       → 修复: {r.remediation}")


# ═══════════════════════════════════════════════════════════════════
#  Step 5: Guardrails PII 检测与脱敏
# ═══════════════════════════════════════════════════════════════════

print_header("Step 5: Guardrails 安全护栏")

# ── PII 检测器 ────────────────────────────────────────────
print_sub("PII 检测器 (PIIDetector)")

pii_detector = PIIDetector()

test_content = '''
客户信息记录:
  姓名: 张三
  邮箱: zhangsan@example.com
  手机: 13812345678
  身份证号(SSN格式): 123-45-6789
  信用卡号: 4111-1111-1111-1111
  IP地址: 192.168.1.100
  API密钥: api_key="my_super_secret_key_12345678"
'''

findings = pii_detector.detect(test_content)
print_result("检测到的 PII", [
    {"类型": f["type"], "匹配内容": f["match"]}
    for f in findings
])

# ── PII 脱敏 ──────────────────────────────────────────────
print_sub("PII 脱敏处理")
redacted_content, redactions = pii_detector.redact(test_content)
print_result("脱敏后内容", redacted_content[:300])
print_result("脱敏记录", [
    {"类型": r["type"], "原文": r["original"], "替换为": r["redacted"]}
    for r in redactions
])

# ── 输入护栏检查 ──────────────────────────────────────────
print_sub("输入护栏 (InputGuardrails)")

input_config = InputGuardrailConfig(
    detect_pii_types=["email", "phone_us", "ssn", "credit_card", "api_key_generic", "password"],
    pii_action=GuardrailAction.REDACT,    # 发现PII → 脱敏处理
    max_input_length=10000,
    banned_phrases=["ignore previous instructions", "hack the system"],
)

input_guardrails = InputGuardrails(input_config, bus=bus)
input_result = input_guardrails.check(test_content)

print_result("动作", input_result.action.value)
print_result("是否阻止", input_result.blocked)
print_result("警告", input_result.warnings)
print_result("违规", input_result.violations)
print_result("脱敏数", len(input_result.redactions))

# ── 输出护栏检查 ──────────────────────────────────────────
print_sub("输出护栏 (OutputGuardrails)")

output_config = OutputGuardrailConfig(
    detect_pii_in_output=True,
    output_pii_action=GuardrailAction.REDACT,
    check_code_safety=True,
    banned_output_patterns=[],
)

output_guardrails = OutputGuardrails(output_config, bus=bus)

# 模拟一段含有 unsafe code 的输出
unsafe_output = '''
这里是Agent生成的代码:
import os
os.system("rm -rf /tmp/test")
eval("print('hello')")
密码是 password="admin123456"
'''

output_result = output_guardrails.check(unsafe_output)
print_result("动作", output_result.action.value)
print_result("是否阻止", output_result.blocked)
print_result("警告", output_result.warnings)
print_result("违规", output_result.violations)

# ── 默认护栏组合 ──────────────────────────────────────────
print_sub("默认护栏组合 (GuardrailsPair)")

guardrails_pair = default_guardrails()
pair_stats = guardrails_pair.stats()
print_result("输入护栏配置", pair_stats["input_config"])
print_result("输出护栏配置", pair_stats["output_config"])

# 使用组合检查
pair_input_result = guardrails_pair.check_input("用户的邮箱是 test@test.com")
pair_output_result = guardrails_pair.check_output("生成的密码是 password='secret123'")

print_result("输入检查结果", {
    "action": pair_input_result.action.value,
    "redactions": len(pair_input_result.redactions),
})
print_result("输出检查结果", {
    "action": pair_output_result.action.value,
    "redactions": len(pair_output_result.redactions),
})


# ═══════════════════════════════════════════════════════════════════
#  Step 6: 知识库 (Knowledge)
# ═══════════════════════════════════════════════════════════════════

print_header("Step 6: 知识库 (Knowledge)")

# ── 6.1 创建知识条目 ──────────────────────────────────────
print_sub("6.1 创建知识条目 (CRUD - Create)")

# 创建本地知识 Provider（使用 demo 专用项目名，避免污染用户真实数据）
knowledge_provider = LocalKnowledgeProvider(project_name="demo-basic")
knowledge_provider.initialize()

# 创建 5 条代表性知识
knowledge_samples = [
    (KnowledgeType.ARCHITECTURE, KnowledgeScope.PROJECT,
     "项目架构", "前后端分离架构，前端 Vue3 + TypeScript，后端 Python FastAPI，共 12 个微服务模块",
     ["架构", "前后端分离", "微服务"], "human", 0.95),
    (KnowledgeType.RISK, KnowledgeScope.FILE,
     "XSS 安全风险", "login.tsx 中用户输入未经 sanitize 直接渲染，存在 XSS 攻击风险",
     ["安全", "XSS", "前端"], "llm", 0.85),
    (KnowledgeType.PATTERN, KnowledgeScope.MODULE,
     "工厂+策略模式", "工厂模式用于创建不同 Handler，策略模式用于切换认证方式（OAuth/JWT/SMS）",
     ["模式", "工厂", "策略"], "learning", 0.80),
    (KnowledgeType.DECISION, KnowledgeScope.PROJECT,
     "ADR-001: 选择 FastAPI", "FastAPI 吞吐量是 Flask 的 3 倍（基准测试），异步支持更优",
     ["ADR", "技术选型", "FastAPI"], "human", 0.90),
    (KnowledgeType.GLOSSARY, KnowledgeScope.PROJECT,
     "项目术语表", "NSP = Network Security Platform，VIDP = Visual Identity Data Platform，Harness = Agent 治理框架",
     ["术语", "缩写"], "human", 0.95),
]

entry_ids = []
for ktype, kscope, title, content, tags, source, confidence in knowledge_samples:
    entry = KnowledgeEntry(
        type=ktype, scope=kscope, title=title,
        content=content, tags=tags, source=source, confidence=confidence,
    )
    eid = knowledge_provider.put(entry)
    entry_ids.append(eid)
    print_result(f"[{ktype.value}/{kscope.value}] {title}", f"id={eid}, 置信度={confidence}, 来源={source}")

# ── 6.2 关键词搜索 ────────────────────────────────────────
print_sub("6.2 关键词搜索 (Query)")

# 搜索"安全"相关知识
query_result = knowledge_provider.query(KnowledgeQuery(query="安全", limit=5))
print_result("搜索关键词", "安全")
print_result("匹配条目数", query_result.total_matches)
print_result("搜索方式", query_result.search_method)
for e in query_result.entries:
    print(f"    └─ [{e.type.value}] {e.title}: {e.content[:50]}...")

# 搜索"架构" + 类型过滤
query_result2 = knowledge_provider.query(
    KnowledgeQuery(query="架构", type_filter=KnowledgeType.ARCHITECTURE, limit=5)
)
print_result("类型过滤搜索", f"关键词='架构' + type=ARCHITECTURE → {query_result2.total_matches} 条")

# ── 6.3 TF-IDF 语义搜索 ──────────────────────────────────
print_sub("6.3 TF-IDF 语义搜索 (Semantic)")

semantic_result = knowledge_provider.semantic_search("前端技术选型和安全防护", limit=3)
print_result("语义搜索关键词", "前端技术选型和安全防护")
print_result("匹配条目数", semantic_result.total_matches)
print_result("搜索方式", semantic_result.search_method)
for e in semantic_result.entries:
    print(f"    └─ [{e.type.value}/{e.scope.value}] {e.title} (置信度={e.confidence})")

# ── 6.4 统计概览 ──────────────────────────────────────────
print_sub("6.4 统计概览 (Stats)")

stats = knowledge_provider.stats()
print_result("总条目数", stats["total_entries"])
print_result("类型分布", stats["types"])
print_result("标签总数", stats["tags"])

# ── 6.5 10种知识类型展示 ──────────────────────────────────
print_sub("6.5 10 种知识类型 × 4 级作用域")
print_result("KnowledgeType", [kt.value for kt in KnowledgeType])
print_result("KnowledgeScope", [ks.value for ks in KnowledgeScope])


# ═══════════════════════════════════════════════════════════════════
#  Step 7: 学习引擎 (Learning)
# ═══════════════════════════════════════════════════════════════════

print_header("Step 7: 学习引擎 (Learning)")

# ── 7.1 创建执行轨迹 ──────────────────────────────────────
print_sub("7.1 创建执行轨迹 (ExperienceStore)")

learning_store = ExperienceStore()

# 创建 3 条轨迹（成功+失败混合）
trace_success = ExecutionTrace(
    workflow_id="wf-demo-success",
    timestamp="2026-06-15T10:00:00",
    duration_ms=5000,
    nodes=[
        TraceNode(node_id="analyst-1", agent_type="analyst", task="分析需求",
                  result_status="completed", duration_ms=1500,
                  files_modified=[], files_read=["req.md"], tokens_used=500,
                  retries=0),
        TraceNode(node_id="coder-1", agent_type="coder", task="编写代码",
                  result_status="completed", duration_ms=3000,
                  files_modified=["main.py"], files_read=["analysis.md"], tokens_used=5000,
                  retries=0),
        TraceNode(node_id="validator-1", agent_type="validator", task="验证代码",
                  result_status="completed", duration_ms=1500,
                  files_modified=[], files_read=["main.py"], tokens_used=200,
                  retries=0),
    ],
    gate_results=[],
    final_status="completed",
)

trace_failure = ExecutionTrace(
    workflow_id="wf-demo-failure",
    timestamp="2026-06-15T10:05:00",
    duration_ms=8000,
    nodes=[
        TraceNode(node_id="coder-2", agent_type="coder", task="编写代码",
                  result_status="failed", duration_ms=6000,
                  files_modified=[], files_read=[], tokens_used=10000,
                  retries=3),  # 过度重试!
    ],
    gate_results=[],
    final_status="failed",
)

trace_mixed = ExecutionTrace(
    workflow_id="wf-demo-mixed",
    timestamp="2026-06-15T10:10:00",
    duration_ms=7000,
    nodes=[
        TraceNode(node_id="analyst-2", agent_type="analyst", task="分析需求",
                  result_status="completed", duration_ms=2000,
                  files_modified=[], files_read=["spec.md"], tokens_used=800,
                  retries=0),
        TraceNode(node_id="coder-3", agent_type="coder", task="编写代码",
                  result_status="completed", duration_ms=4000,
                  files_modified=["auth.py"], files_read=[], tokens_used=6000,
                  retries=1),
    ],
    gate_results=[],
    final_status="completed",
)

learning_store.store(trace_success)
learning_store.store(trace_failure)
learning_store.store(trace_mixed)

store_stats = learning_store.stats()
print_result("轨迹总数", store_stats["total_traces"])
print_result("成功率", f"{store_stats['success_rate']:.1%}")

# ── 7.2 反模式检测 ────────────────────────────────────────
print_sub("7.2 反模式检测 (AntiPatternDetector)")

detector = AntiPatternDetector()
antipatterns = detector.detect(trace_failure, token_budget=200000)
print_result("检测到的反模式数", len(antipatterns))
for ap in antipatterns:
    print_result(f"  反模式 [{ap.type}]", f"置信度={ap.confidence:.2f}")
    print(f"      描述: {ap.description}")
    print(f"      建议: {ap.suggested_action}")

# ── 7.3 学习引擎闭环 ──────────────────────────────────────
print_sub("7.3 学习引擎闭环 (LearningEngine.learn → Knowledge 沉淀)")

# 创建带知识沉淀的学习引擎
learning_engine = LearningEngine(
    store=learning_store,
    knowledge_provider=knowledge_provider,
    token_budget=200000,
)

recommendations = learning_engine.learn(trace_failure)
print_result("学习推荐数", len(recommendations))
for rec in recommendations:
    print_result(f"  推荐 [{rec.type}]", f"置信度={rec.confidence:.2f}")
    print(f"      描述: {rec.description[:60]}...")
    print(f"      建议: {rec.suggested_action[:60]}...")

# 检查知识沉淀——高置信度推荐是否已写入知识库
print_sub("7.3b 检查知识沉淀（learning → knowledge）")
persisted_result = knowledge_provider.query(
    KnowledgeQuery(query="", source_filter="learning", limit=10)
)
print_result("由学习引擎沉淀的知识条目数", persisted_result.total_matches)
for e in persisted_result.entries:
    print(f"    └─ [{e.type.value}] {e.title}: {e.content[:50]}... (来源={e.source})")

# ── 7.4 校准预估 ──────────────────────────────────────────
print_sub("7.4 校准预估 (PredictionCalibrator)")

estimates = learning_engine.get_calibrated_estimates()
print_result("已校准的 Agent 类型数", len(estimates))
for agent_type, params in estimates.items():
    print_result(f"  {agent_type}", {
        "平均Token": int(params.get("avg_tokens", 0)),
        "平均耗时(ms)": int(params.get("avg_duration_ms", 0)),
        "样本数": params.get("sample_count", 0),
    })


# ═══════════════════════════════════════════════════════════════════
#  总结
# ═══════════════════════════════════════════════════════════════════

print_header("Demo 总结")
print(f"""
  harness-cook v{__version__} 基础 Demo 完成！

  展示的核心功能:
    ✅ Agent 注册 — 两种方式(装饰器 + 手动)
    ✅ DAG 工作流 — 3节点(分析→编码→验证) + 2条边
    ✅ DAGEngine 执行 — 拓扑排序 + 逐步执行 + 产出物跟踪
    ✅ ComplianceEngine — 安全/隐私合规扫描 + 违规报告
    ✅ Guardrails — PII检测/脱敏 + 输入/输出护栏 + 默认组合
    ✅ 知识库 — 5类知识 CRUD + 关键词搜索 + TF-IDF 语义搜索 + 统计概览
    ✅ 学习引擎 — 轨迹记录 + 反模式检测 + 经验沉淀到知识库 + 预估校准

  下一步:
    → 运行 playground/demo_mcp.py 了解 MCP Server 集成
    → 运行 playground/demo_cli.sh 了解 CLI 命令行操作
    → 运行 harness knowledge types 查看 10 种知识类型
    → 运行 harness learn stats 查看学习统计概览
    → 查看 playground/demo_workflow.yaml 了解 YAML 工作流定义
""")