"""
harness-bridge — Hermes Agent → harness-cook 桥接脚本

命令行入口，让 Hermes Agent 通过 terminal 执行本脚本调用 harness-cook 核心能力。

用法:
    python bridge.py <command> [args]

子命令:
    check [path]       — 运行合规检查 + 安全护栏扫描
    audit [query]      — 查看审计日志
    run <workflow.yaml> — 执行编排流程
    plan <workflow.yaml> — 可视化 DAG 拓扑
    status             — 显示 harness 运行状态
    version            — 显示版本号
"""

import signal
import sys
import os
import json
import argparse
import subprocess
import textwrap
from pathlib import Path
from datetime import datetime

# ─── PYTHONPATH 设置 ────────────────────────────────────
# 核心包在项目的 packages/core/ 下
# 优先使用 $CLAUDE_PROJECT_DIR（Claude Code 自动设置），确保跨机器可移植
HARNESS_ROOT = os.environ.get("CLAUDE_PROJECT_DIR", str(Path(__file__).resolve().parent.parent.parent))
HARNESS_CORE = str(Path(HARNESS_ROOT) / "packages" / "core")
if HARNESS_CORE not in sys.path:
    sys.path.insert(0, HARNESS_CORE)


def _import_harness():
    """导入 harness 核心包，失败时给出友好提示"""
    try:
        import harness
        return harness
    except ImportError as e:
        print(f"❌ 无法导入 harness 包: {e}")
        print(f"   PYTHONPATH 已设置为: {HARNESS_CORE}")
        print(f"   请确认 packages/core/harness/ 目录存在")
        sys.exit(1)


class _ScanTimeout(Exception):
    """单文件扫描超时"""
    pass


def _scan_timeout_handler(signum, frame):
    raise _ScanTimeout("scan timed out")


def cmd_check(args):
    """运行合规检查 + 安全护栏扫描"""
    harness = _import_harness()
    from harness.compliance import ComplianceEngine, RulePack
    from harness.rule_packs import get_coding_pack, get_security_pack, get_data_pack, get_devops_pack, get_architecture_pack
    from harness.guardrails import GuardrailsPair, default_guardrails
    from harness.types import Artifact
    from harness.bus import EventBus

    path = args.path or "."
    path = Path(path).resolve()

    if not path.exists():
        print(f"❌ 路径不存在: {path}")
        sys.exit(1)

    # 收集文件
    artifacts = []
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            artifacts.append(Artifact(
                type="code",
                path=str(path),
                content=content,
            ))
        except Exception as e:
            print(f"❌ 无法读取文件 {path}: {e}")
            sys.exit(1)
    elif path.is_dir():
        # 扫描目录中的代码文件
        extensions = {".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".java",
                  ".go", ".rs", ".rb", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".kt", ".kts",
                  ".yaml", ".yml", ".json", ".md", ".sql", ".sh", ".dockerfile"}
        count = 0
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in extensions:
                # 限制文件大小（超过100KB跳过）
                if f.stat().st_size > 100_000:
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    artifacts.append(Artifact(
                        type="code",
                        path=str(f.relative_to(path)),
                        content=content,
                    ))
                    count += 1
                except Exception:
                    continue
        if count == 0:
            print(f"⚠️  目录 {path} 中未找到可扫描的代码文件")
            return
        print(f"📂 扫描目录: {path} ({count} 个文件)")

    if not artifacts:
        print("⚠️  无可扫描的文件")
        return

    # 合规检查 — 逐文件 scan_quick + 超时保护
    bus = EventBus()
    engine = ComplianceEngine(bus=bus)
    engine.load_pack(get_coding_pack())
    engine.load_pack(get_security_pack())
    engine.load_pack(get_data_pack())
    engine.load_pack(get_devops_pack())
    engine.load_pack(get_architecture_pack())

    print("\n╔══════════════════════════════════════════╗")
    print("║        合规检查 (Compliance Scan)        ║")
    print("╚══════════════════════════════════════════╝")

    # 逐文件 scan_quick，每文件最多 5 秒超时
    all_results = []
    skipped = 0
    old_handler = signal.signal(signal.SIGALRM, _scan_timeout_handler)
    for art in artifacts:
        if len(art.content) > 50000:  # 跳过过大文件
            skipped += 1
            continue
        signal.alarm(5)
        try:
            file_results = engine.scan_quick(art.content, path=art.path)
            all_results.extend(file_results)
        except _ScanTimeout:
            skipped += 1
        except Exception:
            skipped += 1
        finally:
            signal.alarm(0)
    signal.signal(signal.SIGALRM, old_handler)

    passed = [r for r in all_results if r.passed]
    violations = [r for r in all_results if not r.passed]

    print(f"\n  总规则应用: {len(all_results)}")
    print(f"  ✅ 通过: {len(passed)}")
    print(f"  ❌ 违规: {len(violations)}")
    if skipped:
        print(f"  ⏭️  跳过: {skipped} 个文件(超时或过大)")

    if violations:
        print(f"\n  ── 违规详情 ──────────────────────────────")
        for v in violations[:20]:  # 最多显示20条
            severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(v.severity, "⚪")
            # ComplianceResult: rule_id, findings, remediation, locations
            loc_info = ""
            if v.locations:
                loc_info = f" (line {v.locations[0].get('line', '?')})"
            finding_text = "; ".join(v.findings) if v.findings else "规则违规"
            print(f"  {severity_icon} [{v.rule_id}]{loc_info}")
            print(f"     {finding_text}")
            if v.remediation:
                print(f"     💡 修复建议: {v.remediation}")

    stats = engine.stats()
    print(f"\n  ── 统计 ──────────────────────────────────")
    print(f"  总扫描次数: {stats['total_scans']}")
    print(f"  总违规数: {stats['total_violations']}")
    print(f"  可自动修复: {stats['total_auto_fixable']}")

    # 安全护栏检查
    print("\n╔══════════════════════════════════════════╗")
    print("║        安全护栏 (Guardrails Check)       ║")
    print("╚══════════════════════════════════════════╝")

    guardrails = default_guardrails()
    total_pii = 0
    total_blocked = 0

    for art in artifacts:
        content_preview = art.content[:2000] if len(art.content) > 2000 else art.content
        output_result = guardrails.check_output(content_preview)
        if output_result.blocked:
            total_blocked += 1
            print(f"  🚫 输出被阻止: {art.path}")
            for violation in output_result.violations[:5]:
                print(f"     - {violation}")
        if output_result.redactions:
            total_pii += len(output_result.redactions)
            print(f"  🔒 PII 脱敏: {art.path} ({len(output_result.redactions)} 项)")
            for red in output_result.redactions[:5]:
                print(f"     - [{red['type']}] {red['original']} → {red['redacted']}")

    if total_blocked == 0 and total_pii == 0:
        print("  ✅ 所有文件通过安全护栏检查")

    # 总结
    print("\n╔══════════════════════════════════════════╗")
    print("║              检查总结                    ║")
    print("╚══════════════════════════════════════════╝")
    status = "PASS" if not violations and total_blocked == 0 else "FAIL"
    status_icon = "✅" if status == "PASS" else "❌"
    print(f"  {status_icon} 状态: {status}")
    print(f"  合规违规: {len(violations)}, PII 脱敏: {total_pii}, 阻止: {total_blocked}")


def cmd_audit(args):
    """查看审计日志"""
    harness = _import_harness()
    from harness.audit import AuditStore

    query = args.query or ""
    store = AuditStore()

    entries = store.search(query=query, limit=20)

    print("╔══════════════════════════════════════════╗")
    print("║          审计日志 (Audit Log)            ║")
    print("╚══════════════════════════════════════════╝")

    if not entries:
        print(f"\n  ⚠️  未找到审计记录 (查询: '{query}')")
        print(f"  审计存储目录: {store._store_dir}")
        print(f"  提示: 审计记录在 Agent 执行任务后自动生成")
        return

    print(f"\n  查询: '{query}' | 找到 {len(entries)} 条记录")
    print(f"  ── 最近记录 ──────────────────────────────")

    for entry in entries:
        ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n  📋 [{ts}] Agent: {entry.agent_id}")
        task_text = entry.task if isinstance(entry.task, str) else str(entry.task)
        print(f"     任务: {task_text[:80]}{'...' if len(task_text) > 80 else ''}")
        if entry.decisions:
            for d in entry.decisions[:3]:
                if isinstance(d, dict):
                    print(f"     决策: {d.get('action', '?')} (置信度: {d.get('confidence', '?')})")
                else:
                    print(f"     决策: {d}")
        if entry.actions:
            for a in entry.actions[:3]:
                if isinstance(a, dict):
                    output_text = a.get('output', '?')
                    if isinstance(output_text, str) and len(output_text) > 50:
                        output_text = output_text[:50] + "..."
                    print(f"     行动: {a.get('tool', '?')} → {output_text}")
                else:
                    print(f"     行动: {a}")
        outcomes = entry.outcomes or {}
        if outcomes:
            if isinstance(outcomes, dict):
                status = outcomes.get("status", "?")
                print(f"     结果: {status}")
            elif isinstance(outcomes, list):
                print(f"     结果: {', '.join(str(o) for o in outcomes[:3])}")
            else:
                print(f"     结果: {outcomes}")


def cmd_run(args):
    """执行编排流程"""
    harness = _import_harness()
    from harness.engine import DAGEngine
    from harness.types import DAGWorkflow, DAGNode, DAGEdge

    workflow_path = args.workflow
    workflow_path = Path(workflow_path).resolve()

    if not workflow_path.exists():
        print(f"❌ 工作流文件不存在: {workflow_path}")
        print(f"   提示: 请提供有效的 YAML 工作流定义文件路径")
        sys.exit(1)

    # 解析 YAML 工作流定义
    try:
        import yaml
    except ImportError:
        # 手动简易解析（不依赖 yaml 包）
        print("⚠️  未安装 PyYAML，尝试手动解析...")
        print("   建议: pip install pyyaml")
        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 尝试 JSON 格式
            data = json.loads(content)
        except json.JSONDecodeError:
            print(f"❌ 无法解析工作流文件 (需要 YAML 或 JSON 格式)")
            sys.exit(1)

    else:
        with open(workflow_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    # 构建 DAGWorkflow 对象
    try:
        nodes = []
        for n in data.get("nodes", []):
            nodes.append(DAGNode(
                id=n["id"],
                agent_type=n.get("agent_type", n.get("agent", "default")),
                task=n.get("task", ""),
                inputs=n.get("inputs", []),
            ))

        edges = []
        for e in data.get("edges", []):
            edges.append(DAGEdge(
                from_node=e.get("from_node", e.get("source", "")),
                to_node=e.get("to_node", e.get("target", "")),
                condition=e.get("condition"),
            ))

        workflow = DAGWorkflow(
            id=data.get("id", "bridge-workflow"),
            name=data.get("name", "Bridge Workflow"),
            nodes=nodes,
            edges=edges,
            global_gate=data.get("global_gate"),
        )
    except Exception as e:
        print(f"❌ 工作流定义格式错误: {e}")
        sys.exit(1)

    # 执行
    print("╔══════════════════════════════════════════╗")
    print("║          执行工作流 (DAG Run)            ║")
    print("╚══════════════════════════════════════════╝")
    print(f"\n  工作流: {workflow.name} (节点: {len(nodes)}, 边: {len(edges)})")

    engine = DAGEngine()
    ctx = engine.execute(workflow)

    # 输出结果
    print(f"\n  ── 执行结果 ──────────────────────────────")
    print(f"  执行ID: {ctx.execution_id}")
    print(f"  耗时: {ctx.duration_ms} ms")
    print(f"  完成节点: {len(ctx.completed_nodes)} / {len(nodes)}")
    print(f"  失败节点: {len(ctx.failed_nodes)}")
    print(f"  升级: {'是' if ctx.escalated else '否'}")

    if ctx.failed_nodes:
        print(f"\n  ── 失败节点详情 ──────────────────────────")
        for node_id in ctx.failed_nodes:
            result = ctx.node_results.get(node_id)
            print(f"  ❌ {node_id}: {result.error if result else '未知错误'}")

    status = "✅ 完成" if not ctx.escalated and not ctx.failed_nodes else "❌ 需关注"
    print(f"\n  {status}")


def cmd_plan(args):
    """可视化 DAG 拓扑"""
    harness = _import_harness()
    from harness.scheduler import SmartScheduler
    from harness.types import DAGWorkflow, DAGNode, DAGEdge

    workflow_path = args.workflow
    workflow_path = Path(workflow_path).resolve()

    if not workflow_path.exists():
        print(f"❌ 工作流文件不存在: {workflow_path}")
        sys.exit(1)

    # 解析 YAML
    try:
        import yaml
    except ImportError:
        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                content = f.read()
            data = json.loads(content)
        except json.JSONDecodeError:
            print(f"❌ 无法解析工作流文件")
            sys.exit(1)
    else:
        with open(workflow_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    try:
        nodes = []
        for n in data.get("nodes", []):
            nodes.append(DAGNode(
                id=n["id"],
                agent_type=n.get("agent_type", n.get("agent", "default")),
                task=n.get("task", ""),
                inputs=n.get("inputs", []),
            ))

        edges = []
        for e in data.get("edges", []):
            edges.append(DAGEdge(
                from_node=e.get("from_node", e.get("source", "")),
                to_node=e.get("to_node", e.get("target", "")),
                condition=e.get("condition"),
            ))

        workflow = DAGWorkflow(
            id=data.get("id", "bridge-plan"),
            name=data.get("name", "Bridge Plan"),
            nodes=nodes,
            edges=edges,
        )
    except Exception as e:
        print(f"❌ 工作流定义格式错误: {e}")
        sys.exit(1)

    scheduler = SmartScheduler()
    plan = scheduler.plan(workflow)

    print("╔══════════════════════════════════════════╗")
    print("║          DAG 拓扑 (Workflow Plan)        ║")
    print("╚══════════════════════════════════════════╝")
    print(f"\n  工作流: {workflow.name}")
    print(f"  节点数: {len(nodes)}")

    # 并行分组
    print(f"\n  ── 并行分组 ──────────────────────────────")
    for i, group in enumerate(plan.parallel_groups):
        group_ids = list(group) if isinstance(group[0], str) else [n.id for n in group]
        print(f"  第 {i + 1} 层: {', '.join(group_ids)}")

    # 关键路径
    if plan.critical_path:
        print(f"\n  ── 关键路径 ──────────────────────────────")
        path_ids = list(plan.critical_path) if isinstance(plan.critical_path[0], str) else [n.id for n in plan.critical_path]
        print(f"  → {' → '.join(path_ids)}")

    # Token 预估
    print(f"\n  ── 资源预估 ──────────────────────────────")
    print(f"  预估 Token: {plan.estimated_tokens}")
    print(f"  预估耗时层数: {len(plan.parallel_groups)}")

    # DAG ASCII 可视化
    print(f"\n  ── DAG 可视化 ──────────────────────────────")
    print("  " + _visualize_dag(nodes, edges))


def _visualize_dag(nodes, edges):
    """简易 DAG ASCII 可视化"""
    lines = []
    # 拓扑排序
    in_degree = {n.id: 0 for n in nodes}
    for e in edges:
        if e.to_node in in_degree:
            in_degree[e.to_node] += 1

    # 按层级输出
    layers = []
    remaining = set(n.id for n in nodes)
    while remaining:
        layer = [nid for nid in remaining if in_degree[nid] == 0]
        if not layer:
            layer = [min(remaining, key=lambda x: in_degree[x])]
        layers.append(sorted(layer))
        for nid in layer:
            remaining.discard(nid)
            for e in edges:
                if e.from_node == nid and e.to_node in in_degree:
                    in_degree[e.to_node] -= 1

    for i, layer in enumerate(layers):
        prefix = "  " if i > 0 else ""
        connector = "↓" if i > 0 else ""
        if i > 0:
            lines.append(f"  {connector}")
        lines.append(f"  [{', '.join(layer)}]")

    return "\n".join(lines)


def cmd_status(args):
    """显示 harness 运行状态"""
    harness = _import_harness()
    from harness.registry import get_registry
    from harness.compliance import ComplianceEngine
    from harness.rule_packs import get_coding_pack, get_security_pack, get_data_pack, get_devops_pack, get_architecture_pack
    from harness.audit import AuditStore
    from harness.bus import get_bus
    from harness.bridge import HarnessBridge

    registry = get_registry()
    bus = get_bus()

    # ── 版本 ──────────────────────────────────────
    version = harness.__version__

    # ── Session ───────────────────────────────────
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    session_id = ""
    session_file = Path(project_dir) / ".harness" / "session_id"
    try:
        if session_file.exists():
            session_id = session_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    # ── 部署状态（持久化，系统级） ────────────────
    bridge = HarnessBridge()
    deploy_status = bridge.status(project_dir=project_dir)

    # ── 规则包 ────────────────────────────────────
    compliance_engine = ComplianceEngine(bus=bus)
    compliance_engine.load_pack(get_coding_pack())
    compliance_engine.load_pack(get_security_pack())
    compliance_engine.load_pack(get_data_pack())
    compliance_engine.load_pack(get_devops_pack())
    compliance_engine.load_pack(get_architecture_pack())
    pack_names = compliance_engine.list_packs()
    total_rules = 0
    packs_info = []
    for pack_name in pack_names:
        pack = compliance_engine.get_pack(pack_name)
        if pack:
            packs_info.append((pack_name, len(pack.rules), pack.category.value))
            total_rules += len(pack.rules)

    # ── 审计记录（持久化，系统级） ────────────────
    audit_store = AuditStore()
    audit_files = list(audit_store._store_dir.rglob("*.json"))

    # 最后活动时间：取最新的审计文件修改时间
    last_activity = ""
    if audit_files:
        try:
            latest = max(audit_files, key=lambda f: f.stat().st_mtime)
            from datetime import datetime
            last_activity = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # ── 运行时组件（进程级内存单例） ──────────────
    agent_stats = registry.stats()
    bus_stats = bus.stats()

    # ── 输出 ──────────────────────────────────────
    print("╔══════════════════════════════════════════╗")
    print("║        Harness 状态 (Status)             ║")
    print("╚══════════════════════════════════════════╝")

    print(f"\n  版本: {version}")
    if session_id:
        print(f"  Session: {session_id[:30]}")

    # 部署状态
    print(f"\n  ── 部署状态 ────────────────────────────────")
    if deploy_status.get("deployed"):
        print(f"  ✅ 已部署 (适配器: {deploy_status.get('adapter', '?')})")
        print(f"  配置文件: {deploy_status.get('settings_path', '?')}")
        hook_types = deploy_status.get("hook_types", [])
        if hook_types:
            print(f"  Hook 类型: {', '.join(hook_types)}")
        print(f"  Hook 数量: {deploy_status.get('total_hooks', 0)}")
    else:
        print(f"  ❌ 未部署 (运行 harness activate 部署)")

    # 规则包
    print(f"\n  ── 规则包 ──────────────────────────────────")
    print(f"  已加载: {len(packs_info)} 个包 (共 {total_rules} 条规则)")
    for pack_name, rules, category in packs_info:
        print(f"    📦 {pack_name}: {rules} 条规则 (类别: {category})")

    # 审计记录
    print(f"\n  ── 审计记录 ────────────────────────────────")
    print(f"  记录数: {len(audit_files)}")
    print(f"  存储目录: {audit_store._store_dir}")
    if last_activity:
        print(f"  最后活动: {last_activity}")

    # 运行时组件
    print(f"\n  ── 运行时组件 ──────────────────────────────")
    agent_count = agent_stats['total_agents']
    if agent_count > 0:
        print(f"  Agent 注册: {agent_count} (激活: {agent_stats['active_agents']}, 就绪: {agent_stats['ready_agents']})")
        all_agents = registry.list_all()
        for agent in all_agents[:5]:
            status_icon = "✅" if agent.is_ready else ("⏸️" if not agent.active else "⚠️")
            caps = [c.value for c in agent.definition.capabilities]
            print(f"    {status_icon} {agent.id} ({agent.definition.name}) [caps: {', '.join(caps[:3])}]")
    else:
        print(f"  Agent 注册: 无 (通过 harness_register 或 @define_agent 注册)")

    subscriber_count = bus_stats['total_subscriptions']
    if subscriber_count > 0:
        by_type = bus_stats.get('subscriptions_by_type', {})
        detail = ', '.join(f'{k}: {v}' for k, v in by_type.items()) if by_type else ''
        print(f"  EventBus: {subscriber_count} 个订阅者 ({detail})")
    else:
        print(f"  EventBus: 就绪 (check/run 时自动激活订阅)")


def cmd_version(args):
    """显示版本号"""
    harness = _import_harness()
    print(f"harness-cook v{harness.__version__}")


def main():
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Hermes→harness-cook 桥接脚本",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # check
    check_parser = subparsers.add_parser("check", help="运行合规检查 + 安全护栏扫描")
    check_parser.add_argument("path", nargs="?", default=".", help="要检查的文件或目录路径")

    # audit
    audit_parser = subparsers.add_parser("audit", help="查看审计日志")
    audit_parser.add_argument("query", nargs="?", default="", help="搜索关键词")

    # run
    run_parser = subparsers.add_parser("run", help="执行编排流程")
    run_parser.add_argument("workflow", help="工作流 YAML 文件路径")

    # plan
    plan_parser = subparsers.add_parser("plan", help="可视化 DAG 拓扑")
    plan_parser.add_argument("workflow", help="工作流 YAML 文件路径")

    # status
    subparsers.add_parser("status", help="显示 harness 运行状态")

    # version
    subparsers.add_parser("version", help="显示版本号")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "check": cmd_check,
        "audit": cmd_audit,
        "run": cmd_run,
        "plan": cmd_plan,
        "status": cmd_status,
        "version": cmd_version,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        print("\n⚠️  操作被中断")
        sys.exit(130)
    except Exception as e:
        # 友好错误输出，不打印 traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"❌ 错误 [{error_type}]: {error_msg}")
        print(f"   提示: 请检查输入参数和 harness-cook 状态")
        sys.exit(1)


if __name__ == "__main__":
    main()