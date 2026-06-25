"""
知识管理 / 规则市场 / 合规报告 / 语言识别 / 验证器 类型系统 Demo

演示 harness-cook 五大模块的核心 API：
  1. 本地知识提供者——10种知识类型的 CRUD + 搜索
  2. 规则市场——团队规则共享和订阅
  3. 合规报告生成——扫描结果 → HTML/JSON 报告
  4. 语言自动识别——LanguageRegistry 多语言 import 识别
  5. 验证器注册表——validator_types 类型系统

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/knowledge-rule-report/demo_knowledge_rule_report.py
"""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, "../../packages/core")

from harness.knowledge import (
    KnowledgeType, KnowledgeScope, KnowledgeEntry,
    KnowledgeQuery, KnowledgeQueryResult, LocalKnowledgeProvider,
)
from harness.rule_market import RuleMarket, RulePackMetadata
from harness.report import HTMLReportGenerator, DOTReportGenerator, DSMReport
from harness.language_registry import LanguageRegistry
from harness.validator_types import (
    IssueSeverity, RequirementPriority,
    CodeLocation, ValidationIssue, Requirement, ChangeDescription,
    ValidationContext, ValidationResult,
    ValidatorRegistry, DestructiveChangeValidator, MaxChangesValidator,
)
from harness.types import ComplianceResult


# ═══════════════════════════════════════════════════════════════
#  Demo 1: 本地知识提供者——10种知识类型的 CRUD + 搜索
# ═════════════════════════════════════════════════════════════════

def demo_knowledge_provider():
    """Demo 1: 本地知识提供者——10种知识类型的 CRUD + 搜索"""
    print("\n" + "=" * 60)
    print("Demo 1: 本地知识提供者——10种知识类型的 CRUD + 搜索")
    print("=" * 60)

    # 使用临时目录避免污染用户真实数据
    demo_dir = tempfile.mkdtemp(prefix="harness-knowledge-demo-")
    original_base = os.path.expanduser("~/.harness/knowledge")

    # 初始化 Provider
    provider = LocalKnowledgeProvider(project_name="demo-project")
    # 临时修改存储路径
    provider._base_dir = demo_dir
    provider.initialize()

    # ── 1.1 创建 10 种知识类型的条目 ──
    print("\n  [1.1] 创建 10 种知识类型条目（CRUD - Create）")

    knowledge_samples = [
        (KnowledgeType.ARCHITECTURE, KnowledgeScope.PROJECT,
         "项目架构", "采用前后端分离架构，前端 Vue3 + TypeScript，后端 Python FastAPI",
         ["架构", "前后端分离"], "human"),
        (KnowledgeType.CONVENTION, KnowledgeScope.PROJECT,
         "编码约定", "变量命名用 camelCase，文件命名用 kebab-case，提交信息用 Conventional Commits",
         ["命名", "规范"], "human"),
        (KnowledgeType.DEPENDENCY, KnowledgeScope.MODULE,
         "依赖关系", "auth 模块依赖 user 模块和 cache 模块，user 模块依赖 database 模块",
         ["依赖", "模块"], "ast"),
        (KnowledgeType.API, KnowledgeScope.FILE,
         "API 定义", "POST /api/auth/login 接收 {email, password}，返回 {token, user}",
         ["API", "认证"], "ast"),
        (KnowledgeType.PATTERN, KnowledgeScope.MODULE,
         "设计模式", "工厂模式用于创建不同类型的 Handler，策略模式用于切换认证方式",
         ["模式", "工厂"], "llm"),
        (KnowledgeType.RISK, KnowledgeScope.FILE,
         "风险知识", "login.tsx 中存在 XSS 风险——用户输入未经 sanitize 直接渲染",
         ["安全", "XSS"], "llm"),
        (KnowledgeType.DECISION, KnowledgeScope.PROJECT,
         "决策记录 ADR-001", "选择 FastAPI 而非 Flask——性能基准测试显示 FastAPI 吞吐量是 Flask 的 3 倍",
         ["ADR", "技术选型"], "human"),
        (KnowledgeType.TASK, KnowledgeScope.MODULE,
         "任务知识", "auth 模块的典型工作流：登录 → Token 生成 → 权限校验 → 会话管理",
         ["工作流", "认证"], "learning"),
        (KnowledgeType.TEST, KnowledgeScope.FILE,
         "测试知识", "login.tsx 需要覆盖：正常登录、密码错误、账号锁定、Token 过期四种场景",
         ["测试", "覆盖"], "human"),
        (KnowledgeType.GLOSSARY, KnowledgeScope.PROJECT,
         "术语表", "NSP = Network Security Platform，VIDP = Visual Identity Data Platform",
         ["术语", "缩写"], "human"),
    ]

    entry_ids = []
    for ktype, kscope, title, content, tags, source in knowledge_samples:
        entry = KnowledgeEntry(
            type=ktype, scope=kscope, title=title,
            content=content, tags=tags, source=source, confidence=0.9,
        )
        eid = provider.put(entry)
        entry_ids.append(eid)
        print(f"    [{ktype.value}/{kscope.value}] {title} → id={eid}")

    # ── 1.2 Read：按 ID 查询条目 ──
    print("\n  [1.2] Read：按 ID 查询条目")
    first_id = entry_ids[0]
    entry = provider.get(first_id)
    print(f"    获取 id={first_id}: {entry.summary()}")
    print(f"    内容摘要: {entry.content[:50]}...")
    print(f"    标签: {entry.tags}")
    print(f"    来源: {entry.source}, 可信度: {entry.confidence}")

    # ── 1.3 Update：更新已有条目 ──
    print("\n  [1.3] Update：更新已有条目")
    entry.content = "采用前后端分离架构，前端 Vue3 + Vite + TypeScript，后端 Python FastAPI（已升级 Vite）"
    entry.tags.append("Vite")
    provider.put(entry)
    updated = provider.get(first_id)
    print(f"    更新后: {updated.content[:60]}...")
    print(f"    新标签: {updated.tags}")

    # ── 1.4 Delete：删除条目 ──
    print("\n  [1.4] Delete：删除条目")
    last_id = entry_ids[-1]
    success = provider.delete(last_id)
    print(f"    删除 id={last_id}: {success}")
    remaining = provider.get(last_id)
    print(f"    再次查询: {remaining} (应为 None)")

    # ── 1.5 关键词搜索 ──
    print("\n  [1.5] 关键词搜索")
    result = provider.query(KnowledgeQuery(query="认证", limit=5))
    print(f"    搜索 '认证': 找到 {result.total_matches} 条, 返回 {len(result.entries)} 条")
    for e in result.entries:
        print(f"      {e.summary()}")

    # ── 1.6 类型过滤搜索 ──
    print("\n  [1.6] 类型过滤搜索")
    result = provider.query(KnowledgeQuery(
        query="", type_filter=KnowledgeType.RISK, limit=10,
    ))
    print(f"    搜索 KnowledgeType.RISK: 找到 {result.total_matches} 条")
    for e in result.entries:
        print(f"      {e.summary()}")

    # ── 1.7 标签过滤搜索 ──
    print("\n  [1.7] 标签过滤搜索")
    result = provider.query(KnowledgeQuery(
        query="", tags_filter=["安全"], limit=10,
    ))
    print(f"    搜索标签 '安全': 找到 {result.total_matches} 条")
    for e in result.entries:
        print(f"      {e.summary()}")

    # ── 1.8 语义搜索（TF-IDF）──
    print("\n  [1.8] 语义搜索（TF-IDF）")
    # 需要至少 3 条条目才能触发 TF-IDF 搜索
    result = provider.semantic_search("前端架构技术选型", limit=3)
    print(f"    语义搜索 '前端架构技术选型': 找到 {result.total_matches} 条, 方法={result.search_method}")
    for e in result.entries:
        print(f"      {e.summary()}")

    # ── 1.9 统计信息 ──
    print("\n  [1.9] 统计信息")
    stats = provider.stats()
    print(f"    总条目: {stats['total_entries']}")
    print(f"    类型分布: {json.dumps(stats['types'], ensure_ascii=False)}")
    print(f"    标签数: {stats['tags']}")

    # ── 1.10 知识类型枚举展示 ──
    print("\n  [1.10] KnowledgeType 10 种类型枚举")
    for kt in KnowledgeType:
        print(f"    {kt.name} = {kt.value}")

    # ── 1.11 KnowledgeScope 4 级范围枚举 ──
    print("\n  [1.11] KnowledgeScope 4 级范围枚举")
    for ks in KnowledgeScope:
        print(f"    {ks.name} = {ks.value}")

    # 清理临时目录
    provider.dispose()
    shutil.rmtree(demo_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
#  Demo 2: 规则市场——团队规则共享和订阅
# ═════════════════════════════════════════════════════════════════

def demo_rule_market():
    """Demo 2: 规则市场——团队规则共享和订阅"""
    print("\n" + "=" * 60)
    print("Demo 2: 规则市场——团队规则共享和订阅")
    print("=" * 60)

    # 使用临时目录
    demo_dir = tempfile.mkdtemp(prefix="harness-market-demo-")
    market = RuleMarket(market_dir=demo_dir)

    # ── 2.1 下载规则包 ──
    print("\n  [2.1] 下载规则包")
    market.download("security-best-practices")
    market.download("coding-conventions", version="2.1.0")
    print("    已下载 2 个规则包")

    # ── 2.2 列出可用规则包 ──
    print("\n  [2.2] 列出可用规则包")
    available = market.list_available()
    print(f"    可用规则包: {len(available)} 个")
    for m in available:
        print(f"      {m.name} v{m.version} by {m.author} — {m.description}")

    # ── 2.3 搜索规则包 ──
    print("\n  [2.3] 搜索规则包")
    results = market.search("security")
    print(f"    搜索 'security': 找到 {len(results)} 个")
    for m in results:
        print(f"      {m.name} — {m.description}")

    # ── 2.4 安装规则包 ──
    print("\n  [2.4] 安装规则包")
    market.install("security-best-practices")
    print("    已安装 'security-best-practices'")

    # ── 2.5 列出已安装规则包 ──
    print("\n  [2.5] 列出已安装规则包")
    installed = market.list_installed()
    print(f"    已安装规则包: {len(installed)} 个")
    for m in installed:
        print(f"      {m.name} v{m.version} by {m.author}")

    # ── 2.6 上传自定义规则包 ──
    print("\n  [2.6] 上传自定义规则包")
    # 创建临时规则文件
    rules_dir = os.path.join(demo_dir, "custom-rules-src")
    os.makedirs(rules_dir, exist_ok=True)
    rules_file = os.path.join(rules_dir, "rules.yaml")
    import yaml
    yaml.dump({
        "name": "my-team-rules",
        "version": "1.0.0",
        "rules": [
            {"id": "team-001", "severity": "high", "description": "团队自定义规则"},
        ],
    }, open(rules_file, "w"))

    market.upload(
        pack_name="my-team-rules",
        rules_file=rules_file,
        author="team-lead",
        description="团队自定义安全规则",
        category="security",
        tags=["team", "custom", "security"],
    )
    print("    已上传 'my-team-rules'")

    # ── 2.7 管理规则源 ──
    print("\n  [2.7] 管理规则源")
    sources = market.list_sources()
    print(f"    默认规则源: {len(sources)} 个")
    for s in sources:
        print(f"      {s}")

    market.add_source("internal", "https://gitlab.internal.company.com/rules")
    sources = market.list_sources()
    print(f"    添加自定义源后: {len(sources)} 个")

    market.remove_source("https://gitlab.internal.company.com/rules")
    sources = market.list_sources()
    print(f"    移除自定义源后: {len(sources)} 个")

    # ── 2.8 卸载规则包 ──
    print("\n  [2.8] 卸载规则包")
    market.uninstall("security-best-practices")
    installed = market.list_installed()
    print(f"    卸载后已安装: {len(installed)} 个")

    # ── 2.9 RulePackMetadata 属性展示 ──
    print("\n  [2.9] RulePackMetadata 属性展示")
    meta = RulePackMetadata(
        name="example-pack",
        version="3.0.0",
        author="harness-cook",
        description="示例规则包元数据",
        category="coding",
        tags=["example", "demo"],
        rating=4.5,
    )
    print(f"    name={meta.name}, version={meta.version}")
    print(f"    author={meta.author}, category={meta.category}")
    print(f"    tags={meta.tags}, rating={meta.rating}")
    print(f"    created_at={meta.created_at}")

    # 清理
    shutil.rmtree(demo_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
#  Demo 3: 合规报告生成——扫描结果 → HTML/JSON 报告
# ═════════════════════════════════════════════════════════════════

def demo_compliance_report():
    """Demo 3: 合规报告生成——扫描结果 → HTML/JSON 报告"""
    print("\n" + "=" * 60)
    print("Demo 3: 合规报告生成——扫描结果 → HTML/JSON 报告")
    print("=" * 60)

    report_dir = tempfile.mkdtemp(prefix="harness-report-demo-")

    # ── 3.1 构造合规扫描结果 ──
    print("\n  [3.1] 构造合规扫描结果（ComplianceResult）")
    scan_results = [
        ComplianceResult(rule_id="SEC-001", passed=False, severity="critical",
                         findings=["发现硬编码密码: password='admin123'"],
                         remediation="使用环境变量替代硬编码密码"),
        ComplianceResult(rule_id="SEC-002", passed=True, severity="high",
                         findings=[]),
        ComplianceResult(rule_id="SEC-003", passed=False, severity="high",
                         findings=["HTTP URL 代替 HTTPS: http://api.example.com"],
                         remediation="将所有 HTTP URL 改为 HTTPS"),
        ComplianceResult(rule_id="COD-001", passed=True, severity="medium",
                         findings=[]),
        ComplianceResult(rule_id="COD-002", passed=False, severity="medium",
                         findings=["变量命名不符合规范: snake_case 代替 camelCase"],
                         remediation="遵循项目编码约定，使用 camelCase"),
        ComplianceResult(rule_id="PERF-001", passed=True, severity="low",
                         findings=[]),
    ]

    passed_count = sum(1 for r in scan_results if r.passed)
    failed_count = len(scan_results) - passed_count
    print(f"    总规则: {len(scan_results)}, 通过: {passed_count}, 失败: {failed_count}")
    for r in scan_results:
        status = "PASS" if r.passed else "FAIL"
        print(f"      [{status}] {r.rule_id} ({r.severity}) — {r.findings or '无问题'}")

    # ── 3.2 HTML 合规报告 ──
    print("\n  [3.2] HTML 合规报告")
    html_gen = HTMLReportGenerator()
    html_path = html_gen.generate_compliance_report(
        scan_results, output_dir=report_dir, title="合规扫描报告 Demo",
    )
    print(f"    HTML 报告已写入: {html_path}")
    print(f"    报告大小: {os.path.getsize(html_path)} bytes")

    # ── 3.3 HTML 报告片段预览 ──
    print("\n  [3.3] HTML 报告片段预览（前 200 字符）")
    with open(html_path, "r") as f:
        content = f.read()
    preview = content[:200].replace("\n", " ")
    print(f"    {preview}...")

    # ── 3.4 构造依赖图 ──
    print("\n  [3.4] 构造依赖图 + 依赖 HTML 报告")

    class SimpleDepGraph:
        """模拟依赖图对象"""
        def __init__(self):
            self.nodes = {
                "auth": "auth 模块",
                "user": "user 模块",
                "cache": "cache 模块",
                "db": "数据库模块",
            }
            self.edges = {
                "auth": ["user", "cache"],
                "user": ["db"],
            }

    dep_graph = SimpleDepGraph()
    dep_html_path = html_gen.generate_dependency_graph(
        dep_graph, output_dir=report_dir, title="依赖图 Demo",
    )
    print(f"    依赖图 HTML 报告: {dep_html_path}")

    # ── 3.5 DOT 格式依赖图 ──
    print("\n  [3.5] DOT 格式依赖图（Graphviz）")
    dot_gen = DOTReportGenerator()
    dot_str = dot_gen.generate_dependency_dot(dep_graph)
    print(f"    DOT 输出:")
    print(dot_str)

    # ── 3.6 DOT 调用图 ──
    print("\n  [3.6] DOT 调用图")

    class SimpleCallGraph:
        def __init__(self):
            self.calls = {
                "login()": ["validate()", "generate_token()"],
                "validate()": ["check_password()"],
            }

    call_graph = SimpleCallGraph()
    call_dot = dot_gen.generate_call_graph_dot(call_graph)
    print(f"    调用图 DOT 输出:")
    print(call_dot)

    # ── 3.7 DSM 依赖结构方阵 ──
    print("\n  [3.7] DSM 依赖结构方阵")
    dsm = DSMReport()
    dsm_text = dsm.generate_dsm(dep_graph, output_format="text")
    print(f"    DSM 文本格式:")
    print(dsm_text)

    dsm_json = dsm.generate_dsm(dep_graph, output_format="json")
    print(f"\n    DSM JSON 格式:")
    print(dsm_json)

    dsm_html_path = None
    dsm_html = dsm.generate_dsm(dep_graph, output_format="html")
    # DSM HTML 是返回字符串，不写入文件
    print(f"\n    DSM HTML 报告大小: {len(dsm_html)} bytes")

    # ── 3.8 审计仪表盘 ──
    print("\n  [3.8] 审计仪表盘")

    class SimpleAuditStats:
        total_tasks = 42
        delivered = 35
        escalated = 3
        auto_fixed = 4
        verification_pass_rate = 0.85

    audit_stats = SimpleAuditStats()
    dashboard_path = html_gen.generate_audit_dashboard(
        audit_stats, output_dir=report_dir, title="审计仪表盘 Demo",
    )
    print(f"    仪表盘 HTML: {dashboard_path}")

    # ── 3.9 JSON 格式扫描结果 ──
    print("\n  [3.9] JSON 格式扫描结果")
    json_results = [
        {
            "rule_id": r.rule_id,
            "passed": r.passed,
            "severity": r.severity,
            "findings": r.findings,
            "remediation": r.remediation,
        }
        for r in scan_results
    ]
    json_str = json.dumps(json_results, indent=2, ensure_ascii=False)
    print(f"    JSON 输出（前 300 字符）:")
    print(f"    {json_str[:300]}...")

    # 清理
    shutil.rmtree(report_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
#  Demo 4: 语言自动识别——LanguageRegistry 多语言 import 识别
# ═════════════════════════════════════════════════════════════════

def demo_language_registry():
    """Demo 4: 语言自动识别——LanguageRegistry 多语言 import 识别"""
    print("\n" + "=" * 60)
    print("Demo 4: 语言自动识别——LanguageRegistry 多语言 import 识别")
    print("=" * 60)

    # ── 4.1 注册内置语言 ──
    print("\n  [4.1] 注册所有内置语言（LanguageRegistry.default()）")
    # 先清空再注册，避免全局状态残留
    LanguageRegistry._languages.clear()
    LanguageRegistry.default()
    print(f"    已注册 {len(LanguageRegistry._languages)} 种语言")

    # ── 4.2 列出所有注册语言 ──
    print("\n  [4.2] 列出所有注册语言")
    for name, config in LanguageRegistry._languages.items():
        extensions = config["extensions"]
        ts_module = config.get("tree_sitter_module") or "(stdlib/regex)"
        import_pattern = config.get("import_pattern") or "(tree-sitter)"
        print(f"    {name}: ext={extensions}, ts={ts_module}, pattern={import_pattern[:40]}{'...' if len(str(import_pattern)) > 40 else ''}")

    # ── 4.3 文件扩展名自动识别 ──
    print("\n  [4.3] 文件扩展名自动识别")
    test_paths = [
        "src/main.py",
        "components/App.tsx",
        "utils/helper.js",
        "models/User.java",
        "cmd/server.go",
        "lib/auth.rs",
        "app/controllers.rb",
        "kernel/main.c",
        "engine/Render.cpp",
        "views/Login.vue",
        "ios/App.swift",
        "flutter/main.dart",
        "web/index.php",
        "spark/Job.scala",
        "game/init.lua",
        "sf/Apex.cls",
    ]
    for path in test_paths:
        result = LanguageRegistry.get_by_extension(path)
        if result:
            lang_name, lang_config = result
            print(f"    {path} → {lang_name}")
        else:
            print(f"    {path} → 未知语言")

    # ── 4.4 获取特定语言配置 ──
    print("\n  [4.4] 获取特定语言配置")
    python_cfg = LanguageRegistry.get("python")
    print(f"    Python 配置: {python_cfg}")

    java_cfg = LanguageRegistry.get("java")
    print(f"    Java 配置: {java_cfg}")

    # ── 4.5 所有支持的文件扩展名 ──
    print("\n  [4.5] 所有支持的文件扩展名")
    all_exts = LanguageRegistry.all_supported_extensions()
    print(f"    总扩展名: {len(all_exts)} 个")
    sorted_exts = sorted(all_exts)
    print(f"    {sorted_exts}")

    # ── 4.6 tree-sitter 语言对象 ──
    print("\n  [4.6] tree-sitter 语言对象（动态导入）")
    # tree-sitter 模块可能未安装，演示降级机制
    for lang_name in ["python", "javascript", "java", "go"]:
        ts_lang = LanguageRegistry.get_tree_sitter_language(lang_name)
        if ts_lang:
            print(f"    {lang_name}: tree-sitter Language 对象已获取")
        else:
            print(f"    {lang_name}: tree-sitter 未安装，降级为正则 fallback")

    # ── 4.7 自定义语言注册 ──
    print("\n  [4.7] 自定义语言注册")
    LanguageRegistry.register(
        name="elixir",
        extensions=[".ex", ".exs"],
        tree_sitter_module="tree_sitter_elixir",
        import_pattern=r'^use\s+([a-zA-Z0-9_.]+)',
    )
    elixir_cfg = LanguageRegistry.get("elixir")
    print(f"    Elixir 注册成功: {elixir_cfg}")

    # 验证识别
    result = LanguageRegistry.get_by_extension("lib/my_module.ex")
    print(f"    lib/my_module.ex → {result[0] if result else '未知'}")

    # 清理自定义注册
    LanguageRegistry._languages.pop("elixir", None)


# ═══════════════════════════════════════════════════════════════
#  Demo 5: 验证器注册表——validator_types 类型系统
# ═════════════════════════════════════════════════════════════════

def demo_validator_types():
    """Demo 5: 验证器注册表——validator_types 类型系统"""
    print("\n" + "=" * 60)
    print("Demo 5: 验证器注册表——validator_types 类型系统")
    print("=" * 60)

    # ── 5.1 枚举类型展示 ──
    print("\n  [5.1] 枚举类型展示")
    print("    IssueSeverity（问题严重度）:")
    for sev in IssueSeverity:
        print(f"      {sev.name} = {sev.value}")

    print("    RequirementPriority（需求优先级）:")
    for pri in RequirementPriority:
        print(f"      {pri.name} = {pri.value}")

    # ── 5.2 CodeLocation 代码定位 ──
    print("\n  [5.2] CodeLocation 代码定位")
    loc = CodeLocation(
        file_path="src/auth/login.tsx", line_number=42,
        column=15, symbol_name="validateCredentials",
    )
    print(f"    display(): {loc.display()}")
    print(f"    file_path={loc.file_path}, line={loc.line_number}, symbol={loc.symbol_name}")

    # ── 5.3 ValidationIssue 验证问题 ──
    print("\n  [5.3] ValidationIssue 验证问题")
    issue_critical = ValidationIssue(
        rule_id="SEC-001", severity=IssueSeverity.CRITICAL,
        message="发现硬编码密码", location=loc,
        autoFixable=False, fix_hint="使用环境变量替代",
    )
    print(f"    rule_id={issue_critical.rule_id}")
    print(f"    severity={issue_critical.severity.value}")
    print(f"    is_blocking={issue_critical.is_blocking()}")
    print(f"    autoFixable={issue_critical.autoFixable}")

    issue_low = ValidationIssue(
        rule_id="COD-002", severity=IssueSeverity.LOW,
        message="命名风格不一致",
    )
    print(f"\n    低严重度问题:")
    print(f"    rule_id={issue_low.rule_id}")
    print(f"    is_blocking={issue_low.is_blocking()}")

    # ── 5.4 Requirement 验证需求 ──
    print("\n  [5.4] Requirement 验证需求")
    req1 = Requirement(
        id="REQ-001", title="无硬编码密码",
        description="代码中不允许包含硬编码的密码或密钥",
        priority=RequirementPriority.MUST,
        category="安全",
        acceptance_criteria=["不含 password= 字样", "不含 api_key= 字样"],
    )
    print(f"    id={req1.id}, priority={req1.priority.value}")
    print(f"    is_mandatory={req1.is_mandatory()}")
    print(f"    acceptance_criteria={req1.acceptance_criteria}")

    req2 = Requirement(
        id="REQ-002", title="代码格式规范",
        priority=RequirementPriority.SHOULD,
        category="格式",
    )
    print(f"\n    SHOULD 优先级: is_mandatory={req2.is_mandatory()}")

    # ── 5.5 ChangeDescription 变更描述 ──
    print("\n  [5.5] ChangeDescription 变更描述")
    change_normal = ChangeDescription(
        file_path="src/auth/login.tsx", change_type="modify",
        diff_summary="修改登录验证逻辑", lines_added=15, lines_removed=5,
    )
    print(f"    正常变更: is_destructive={change_normal.is_destructive()}")

    change_destructive = ChangeDescription(
        file_path="src/legacy/old_module.py", change_type="delete",
        diff_summary="删除旧模块", lines_added=0, lines_removed=120,
    )
    print(f"    破坏性变更: is_destructive={change_destructive.is_destructive()}")

    # ── 5.6 ValidationContext 验证上下文 ──
    print("\n  [5.6] ValidationContext 验证上下文")
    ctx = ValidationContext(
        changes=[change_normal, change_destructive],
        requirements=[req1, req2],
        knowledge={"security_rules": ["SEC-001", "SEC-002"]},
        agent_id="claude-code",
        task="重构认证模块",
    )
    print(f"    has_destructive_changes={ctx.has_destructive_changes()}")
    print(f"    affected_files={ctx.affected_files()}")
    print(f"    mandatory_requirements={len(ctx.mandatory_requirements())} 个")
    for r in ctx.mandatory_requirements():
        print(f"      {r.id}: {r.title} ({r.priority.value})")

    # ── 5.7 ValidatorRegistry 注册和执行 ──
    print("\n  [5.7] ValidatorRegistry 注册和执行")
    registry = ValidatorRegistry()

    # 注册内置 Validator（不注册 defaults，避免依赖 compliance/guardrails）
    registry.register_validator(DestructiveChangeValidator())
    registry.register_validator(MaxChangesValidator(max_changes=200, max_files=20))
    print(f"    已注册 Validator: {registry.list_validators()}")

    # 执行验证
    results = registry.run_validation(ctx)
    print(f"    验证结果数: {len(results)}")
    for r in results:
        print(f"      {r.summary()}")

    # ── 5.8 判定最终 pass/fail ──
    print("\n  [5.8] 判定最终 pass/fail")
    final_pass = registry.judge_results(results)
    print(f"    最终判定: {'PASS' if final_pass else 'FAIL'}")

    # ── 5.9 ValidationResult 分析 ──
    print("\n  [5.9] ValidationResult 分析")
    # 手动构造一个更丰富的 ValidationResult 来展示分析方法
    rich_result = ValidationResult(
        validator_id="demo-validator",
        passed=False,
        issues=[
            ValidationIssue(rule_id="SEC-001", severity=IssueSeverity.CRITICAL,
                            message="硬编码密码", autoFixable=False),
            ValidationIssue(rule_id="SEC-002", severity=IssueSeverity.HIGH,
                            message="HTTP URL", autoFixable=True, fix_hint="改为 HTTPS"),
            ValidationIssue(rule_id="COD-001", severity=IssueSeverity.MEDIUM,
                            message="命名不一致", autoFixable=True),
            ValidationIssue(rule_id="DOC-001", severity=IssueSeverity.LOW,
                            message="缺少注释"),
        ],
        fixed_issues=0,
    )
    print(f"    summary(): {rich_result.summary()}")
    print(f"    blocking_issues: {len(rich_result.blocking_issues())} 个")
    print(f"    warnings: {len(rich_result.warnings())} 个")
    print(f"    info: {len(rich_result.info())} 个")
    print(f"    auto_fixable_issues: {len(rich_result.auto_fixable_issues())} 个")
    for issue in rich_result.auto_fixable_issues():
        print(f"      {issue.rule_id}: {issue.message} (fix_hint={issue.fix_hint})")

    # ── 5.10 注册器统计 ──
    print("\n  [5.10] 注册器统计")
    stats = registry.stats()
    print(f"    total_validators={stats['total_validators']}")
    print(f"    validator_ids={stats['validator_ids']}")

    # ── 5.11 取消注册 ──
    print("\n  [5.11] 取消注册")
    success = registry.unregister_validator("max-changes")
    print(f"    取消 max-changes: {success}")
    print(f"    剩余 Validator: {registry.list_validators()}")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Harness Knowledge / RuleMarket / Report / Language / Validator Demo")
    print("=" * 60)

    demo_knowledge_provider()
    demo_rule_market()
    demo_compliance_report()
    demo_language_registry()
    demo_validator_types()

    print("\n" + "=" * 60)
    print("所有 Demo 完成")
    print("=" * 60)
