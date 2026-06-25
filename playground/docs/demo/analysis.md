# 代码分析 Demo

> 调用图构建、污点追踪、God Class 检测、变更影响分析——四大代码分析引擎

**定位**：代码分析展示 harness-cook 的静态分析能力——从调用关系追踪到安全污点流，从反模式检测到变更影响传播。

完整可运行脚本见项目 `examples/analysis/` 目录（`demo_analysis.py`）。

---

## Demo 1：调用图构建

```python
from harness.call_graph import CallGraphBuilder, CallGraph

code = '''
class UserService:
    def get_user(self, user_id):
        return self._fetch_from_db(user_id)

    def _fetch_from_db(self, user_id):
        return db.query("SELECT * FROM users WHERE id = ?", user_id)

    def update_user(self, user_id, data):
        user = self.get_user(user_id)
        return self._save_to_db(user, data)
'''

builder = CallGraphBuilder()
graph = builder.scan_python(code, filepath="user_service.py")

print(f"定义数: {len(graph.definitions)}")
for caller, callees in graph.calls.items():
    print(f"  {caller} → {callees}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `graph.definitions` | 类和方法定义列表 |
| `graph.calls` | 调用关系：`get_user → _fetch_from_db`、`update_user → get_user / _save_to_db` |
| `graph.file_methods` | 文件 → 方法映射 |

---

## Demo 2：污点追踪

```python
from harness.taint import TaintTracker, TaintSource, TaintSink
from harness.taint import TaintSourceType, TaintSinkType, BUILTIN_SOURCES, BUILTIN_SINKS

# 内置 source/sink
dangerous_code = '''
user_input = input("Enter command: ")
os.system(user_input)

password = request.form.get("password")
db.execute("SELECT * FROM users WHERE pwd = " + password)
'''

tracker = TaintTracker()
findings = tracker.track_python(dangerous_code, filepath="vulnerable.py")

for f in findings:
    print(f"{f.source_type.value} → {f.sink_type.value}: {f.description}")
    print(f"  源: 变量 '{f.source_var}' (行 {f.source_line})")
    print(f"  汇: {f.sink_call} (行 {f.sink_line})")

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
```

### 预期输出

| 污点流 | source → sink | 安全风险 |
|--------|---------------|---------|
| `user_input → os.system()` | USER_INPUT → OS_SYSTEM | 命令注入 |
| `request.form → db.execute()` | REQUEST_INPUT → DB_EXECUTE | SQL注入 |

---

## Demo 3：God Class 检测

```python
from harness.god_class_metrics import GodClassMetrics, ClassMetrics, CompoundThresholds

metrics = GodClassMetrics()

# 正常类
normal = ClassMetrics(
    class_name="UserService",
    line=1,
    atfd=2,     # 外部数据访问少
    wmc=8,       # 方法复杂度适中
    tcc=0.7,     # 方法间紧耦合
    method_count=4,
)

# God Class
god = ClassMetrics(
    class_name="ProjectManager",
    line=10,
    atfd=15,    # 大量访问外部数据
    wmc=50,      # 极高复杂度
    tcc=0.1,     # 方法间几乎无耦合
    method_count=20,
)

print(f"UserService 是 God Class? {metrics.is_god_class(normal)}")
print(f"ProjectManager 是 God Class? {metrics.is_god_class(god)}")

# 自定义阈值
thresholds = CompoundThresholds(atfd_few=3, wmc_high=20, tcc_low=0.3)
```

### 预期输出

| 类名 | ATFD | WMC | TCC | God Class? |
|------|------|-----|-----|-----------|
| UserService | 2 | 8 | 0.7 | ❌ No |
| ProjectManager | 15 | 50 | 0.1 | ✅ Yes |

**判定逻辑**：ATFD > ATFD_FEW ∧ WMC > WMC_HIGH ∧ TCC < TCC_LOW → God Class

---

## Demo 4：变更影响分析

```python
from harness.impact_analyzer import ImpactAnalyzer
from harness.impact_types import ImpactAnalysis, ImpactRisk, DependencyGraph

# 程序化构建依赖图
graph = DependencyGraph()
graph.add_node("app.py", is_entry_point=True)
graph.add_node("user_service.py")
graph.add_node("db_utils.py")
graph.add_node("config.py")
graph.add_edge("app.py", "user_service.py")
graph.add_edge("user_service.py", "db_utils.py")
graph.add_edge("db_utils.py", "config.py")

# 修改 config.py 影响谁?
print(f"config.py 被依赖: {graph.get_reverse_dependencies('config.py')}")

analysis = ImpactAnalysis(
    change_files=["config.py"],
    direct_impacts={"db_utils.py"},
    indirect_impacts={"user_service.py", "app.py"},
    risk=ImpactRisk(level="MEDIUM", reason="核心配置变更影响3个文件"),
    affected_count=3,
    requires_review=True,
)
print(f"影响分析: {analysis.summary()}")
```

### 预期输出

| 观察项 | 期望值 |
|--------|--------|
| `graph.get_dependents('config.py')` | `['app.py', 'db_utils.py']` |
| `analysis.direct_impacts` | `{'db_utils.py'}` |
| `analysis.indirect_impacts` | `{'user_service.py', 'app.py'}` |
| `analysis.requires_review` | `True` |

---

## 适用场景

| 场景 | 推荐引擎 |
|------|---------|
| 安全审计——检测用户输入到危险函数的数据流 | 污点追踪 |
| 代码质量——识别 God Class 反模式 | God Class 检测 |
| 变更评估——修改核心文件前评估影响范围 | 影响分析 |
| 依赖分析——构建方法级调用关系图 | 调用图 |

---

## 相关导航

- 📖 原理 → [引擎总线](/guide/engine-bus) · [合规层](/guide/compliance-layer)
- 🏃 跑代码 → [examples/analysis/](../../examples/analysis/)
- 🎓 方法 → [合规扫描](/tutorial/compliance-scan)
