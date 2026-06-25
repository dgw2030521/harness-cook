"""
代码分析 Demo 示例

演示 harness-cook 的四大代码分析引擎——调用图构建、污点追踪、God Class 检测、变更影响分析。

运行方式:
  cd packages/core
  PYTHONPATH=. python3 ../../examples/analysis/demo_analysis.py

输出:
  - 调用图构建——CallGraphBuilder.scan_python() 方法级调用关系
  - 污点追踪——TaintTracker.track_python() 数据流安全分析
  - God Class 检测——GodClassMetrics 三维指标 (ATFD/WMC/TCC)
  - 变更影响分析——ImpactAnalyzer 依赖图 + 影响传播路径
"""

import sys
sys.path.insert(0, "../../packages/core")

from harness.call_graph import CallGraphBuilder, CallGraph
from harness.taint import TaintTracker, TaintSource, TaintSink, TaintFinding
from harness.taint import TaintSourceType, TaintSinkType, BUILTIN_SOURCES, BUILTIN_SINKS
from harness.god_class_metrics import GodClassMetrics, ClassMetrics, CompoundThresholds
from harness.impact_analyzer import FileImpactAnalyzer
from harness.impact_types import ImpactAnalysis, ImpactRisk, ImpactRiskLevel, DependencyGraph


def demo_call_graph():
    """Demo 1: 调用图构建——方法级调用关系"""
    print("\n" + "=" * 60)
    print("Demo 1: 调用图构建——CallGraphBuilder.scan_python()")
    print("=" * 60)

    code = '''
class UserService:
    def get_user(self, user_id):
        return self._fetch_from_db(user_id)

    def _fetch_from_db(self, user_id):
        return db.query("SELECT * FROM users WHERE id = ?", user_id)

    def update_user(self, user_id, data):
        user = self.get_user(user_id)
        return self._save_to_db(user, data)

    def _save_to_db(self, user, data):
        return db.update("users", user.id, data)

def main():
    svc = UserService()
    user = svc.get_user(1)
    svc.update_user(1, {"name": "new"})
'''

    builder = CallGraphBuilder()
    graph = builder.scan_python(code, filepath="user_service.py")

    print(f"  定义数: {len(graph.definitions)}")
    print(f"  调用关系:")
    for caller, callees in graph.calls.items():
        print(f"    {caller} → {callees}")
    print(f"  文件方法: {dict(graph.file_methods)}")


def demo_taint_tracking():
    """Demo 2: 污点追踪——数据流安全分析"""
    print("\n" + "=" * 60)
    print("Demo 2: 污点追踪——TaintTracker.track_python()")
    print("=" * 60)

    # 内置污染源和汇聚点
    print(f"  内置 Source 类型: {[s.type.value for s in BUILTIN_SOURCES[:5]]}")
    print(f"  内置 Sink 类型: {[s.type.value for s in BUILTIN_SINKS[:5]]}")

    # 检测危险数据流
    dangerous_code = '''
user_input = input("Enter command: ")
os.system(user_input)

password = request.form.get("password")
db.execute("SELECT * FROM users WHERE pwd = " + password)
'''

    tracker = TaintTracker()
    findings = tracker.track_python(dangerous_code, filepath="vulnerable.py")

    print(f"  检测到污点流: {len(findings)}")
    for f in findings:
        print(f"    {f.source_type.value} → {f.sink_type.value}: {f.description}")
        print(f"    源: 变量 '{f.source_var}' (行 {f.source_line})")
        print(f"    汇: 行 {f.sink_line} ({f.sink_type.value})")

    # 安全代码——无污点流
    safe_code = '''
def safe_greet(name):
    print(f"Hello, {name}")
    return True
'''

    safe_findings = tracker.track_python(safe_code, filepath="safe.py")
    print(f"  安全代码检测: {len(safe_findings)} findings (无污点流)")

    # 自定义 source/sink
    custom_source = TaintSource(
        TaintSourceType.USER_INPUT, r"my_custom_input",
        "Custom input source",
    )
    custom_sink = TaintSink(
        TaintSinkType.EVAL, r"my_custom_eval",
        "Custom eval sink",
    )
    tracker2 = TaintTracker(sources=[custom_source], sinks=[custom_sink])
    custom_code = '''
x = my_custom_input("test")
my_custom_eval(x)
'''
    findings2 = tracker2.track_python(custom_code)
    print(f"  自定义 source/sink 检测: {len(findings2)} findings")


def demo_god_class():
    """Demo 3: God Class 检测——三维指标"""
    print("\n" + "=" * 60)
    print("Demo 3: God Class 检测——ATFD/WMC/TCC 三维指标")
    print("=" * 60)

    metrics = GodClassMetrics()

    # 正常类——低 ATFD、中等 WMC、高 TCC
    normal = ClassMetrics(
        class_name="UserService",
        line=1,
        atfd=2,      # 访问的外部数据少
        wmc=8,        # 方法复杂度适中
        tcc=0.7,      # 方法间紧耦合
        method_count=4,
    )
    result_normal = metrics.is_god_class(normal)
    print(f"  正常类 UserService: atfd={normal.atfd}, wmc={normal.wmc}, tcc={normal.tcc:.1f}")
    print(f"    是 God Class? {result_normal}")

    # God Class——高 ATFD、高 WMC、低 TCC
    god = ClassMetrics(
        class_name="ProjectManager",
        line=10,
        atfd=15,     # 大量访问外部数据
        wmc=50,       # 方法复杂度极高
        tcc=0.1,      # 方法间几乎无耦合
        method_count=20,
    )
    result_god = metrics.is_god_class(god)
    print(f"  God Class ProjectManager: atfd={god.atfd}, wmc={god.wmc}, tcc={god.tcc:.1f}")
    print(f"    是 God Class? {result_god}")

    # 自定义阈值
    thresholds = CompoundThresholds(atfd_few=3, wmc_high=20, tcc_low=0.3)
    print(f"  默认阈值: ATFD_FEW={metrics.thresholds.atfd_few}, WMC_HIGH={metrics.thresholds.wmc_high}, TCC_LOW={metrics.thresholds.tcc_low}")


def demo_impact_analyzer():
    """Demo 4: 变更影响分析——依赖图 + 影响传播"""
    print("\n" + "=" * 60)
    print("Demo 4: 变更影响分析——依赖图 + 影响传播路径")
    print("=" * 60)

    # ImpactAnalyzer 需要真实项目目录
    # 这里用程序化构建依赖图演示 API
    graph = DependencyGraph()
    graph.add_node("app.py", is_entry_point=True)
    graph.add_node("user_service.py")
    graph.add_node("db_utils.py")
    graph.add_node("config.py")
    graph.add_node("logger.py")
    graph.add_edge("app.py", "user_service.py")
    graph.add_edge("app.py", "config.py")
    graph.add_edge("user_service.py", "db_utils.py")
    graph.add_edge("db_utils.py", "config.py")
    graph.add_edge("db_utils.py", "logger.py")

    stats = graph.stats()
    print(f"  依赖图统计: {stats}")
    print(f"  app.py 依赖: {graph.get_dependencies('app.py')}")
    print(f"  config.py 被依赖: {graph.get_dependents('config.py')}")

    # 影响分析——修改 config.py 影响谁?
    analysis = ImpactAnalysis(
        change_files=["config.py"],
        direct_impacts={"app.py", "db_utils.py"},
        indirect_impacts={"user_service.py", "logger.py"},
        risk=ImpactRisk(level=ImpactRiskLevel.MEDIUM, reason="核心配置变更影响4个文件"),
        affected_count=4,
        requires_review=True,
    )
    print(f"  影响分析: {analysis.summary()}")
    print(f"  直接影响: {analysis.direct_impacts}")
    print(f"  间接影响: {analysis.indirect_impacts}")
    print(f"  需要审批: {analysis.requires_review}")


if __name__ == "__main__":
    print("=" * 60)
    print("Harness Analysis Demo")
    print("=" * 60)
    demo_call_graph()
    demo_taint_tracking()
    demo_god_class()
    demo_impact_analyzer()
    print("\n✅ 所有代码分析 Demo 完成")
