# 依赖注入模式

> harness-cook 的组装策略——全局单例适合快速上手，依赖注入适合生产环境，两种模式的边界和迁移路径。

**快速导航**：[📖 原理（本页）](#原理) · [🎓 使用方法](/tutorial/dependency-injection) · [📖 相关](/guide/engine-bus)

---

## 原理

### 双模式设计

harness-cook 核心模块同时支持两种使用方式：

| 模式 | 入口 | 适用场景 | 特点 |
|------|------|---------|------|
| 全局单例 | `get_registry()` / `get_bus()` | 测试、简单场景、快速原型 | 隐式依赖，零配置即可运行 |
| 依赖注入 | `DAGEngine(registry=..., bus=...)` | 生产环境、需要隔离 | 显式依赖，可控、可测试 |

**核心原则**：不要混用两种模式——选择依赖注入后，就不再调用 `get_xxx()` 全局单例。

### 全局单例模式

```python
from harness import get_registry, get_bus, DAGEngine

# 零配置——所有模块自动使用全局单例
engine = DAGEngine()          # registry → get_registry(), bus → get_bus()
engine.execute(workflow)
```

全局单例在第一次调用 `get_xxx()` 时创建，之后一直存在。生命周期管理：

- `get_registry()` → 创建/获取全局 AgentRegistry
- `get_bus()` → 创建/获取全局 EventBus
- `reset_registry()` → 重置全局 AgentRegistry（测试用）
- `reset_bus()` → 重置全局 EventBus（测试用）

### 依赖注入模式

```python
from harness import AgentRegistry, EventBus, DAGEngine, GateEngine

# 显式创建依赖
bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)

# 注入到引擎
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)
engine.execute(workflow)
```

依赖注入的优势：

- **测试隔离**：每个测试创建独立的 EventBus 和 Registry，无全局状态污染
- **依赖图清晰**：所有依赖关系是单向的，可从顶层入口追踪到每个模块
- **可替换**：可以注入 mock 实现替换真实依赖

### 核心模块的注入接口

所有核心模块的构造函数都接受可选的依赖参数，默认回退到全局单例：

#### DAGEngine

```python
DAGEngine(
    registry: Optional[AgentRegistry] = None,         # 默认: get_registry()
    gate_engine: Optional[GateEngine] = None,          # 默认: GateEngine(bus=bus)
    bus: Optional[EventBus] = None,                    # 默认: get_bus()
    rollback_engine: Optional[RollbackEngine] = None,  # 默认: get_rollback_engine()
    downgrade_engine: Optional[DowngradeEngine] = None, # 默认: None
    rollback_policy: RollbackPolicy = RollbackPolicy.NONE,
    max_workers: int = 1,
)
```

#### GateEngine

```python
GateEngine(
    bus: Optional[EventBus] = None,            # 默认: get_bus()
    max_retries_override: Optional[int] = None,
)
```

#### SkillRegistry

```python
SkillRegistry(
    bus: Optional[EventBus] = None,            # 默认: get_bus()
)
```

#### AgentRegistry

```python
AgentRegistry(
    bus: Optional[EventBus] = None,            # 默认: get_bus()
)
```

#### LearningEngine

```python
LearningEngine(
    store: Optional[ExperienceStore] = None,
    bus: Optional[EventBus] = None,            # 默认: get_bus()
    token_budget: int = 200000,
    knowledge_provider: Optional[LocalKnowledgeProvider] = None,
)
```

#### GateManager

```python
GateManager(
    notifier: Optional[INotifier] = None,      # 默认: LocalNotifier()
    downgrade: Optional[AutoDowngrade] = None,  # 默认: AutoDowngrade()
)
```

### 何时用哪种模式

| 场景 | 推荐模式 | 原因 |
|------|---------|------|
| CLI 工具 / MCP Server 启动 | 全局单例 | 简单快速，单一进程无隔离需求 |
| 单元测试 | 依赖注入 | 测试隔离，避免全局状态污染 |
| 多项目并行运行 | 依赖注入 | 每个项目需要独立的 Registry 和 EventBus |
| 生产环境 Web 服务 | 依赖注入 | 依赖图可控，便于监控和替换 |
| 快速原型/脚本 | 全局单例 | 零配置，快速上手 |

---

## 配置

### 测试场景的依赖注入

```python
def test_my_feature():
    # 创建测试专用的 EventBus
    test_bus = EventBus()

    # 创建测试专用的 Registry
    test_registry = AgentRegistry(bus=test_bus)

    # 注入到引擎——完全隔离
    engine = DAGEngine(registry=test_registry, bus=test_bus)

    # 执行测试...
    result = engine.execute(workflow)

    # 清理
    reset_registry()
    reset_bus()
```

### 生产环境的依赖注入

```python
# 应用启动点——组装所有依赖
bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)
skill_registry = SkillRegistry(bus=bus)

# DAG 引擎——注入所有依赖
engine = DAGEngine(
    registry=registry,
    gate_engine=gate_engine,
    bus=bus,
    max_workers=4,
)

# 所有模块共享同一个 EventBus——事件全局可见
```

### 从全局单例迁移到依赖注入

迁移步骤：

1. **识别顶层入口**：找到应用启动点（CLI、MCP、Web）
2. **创建依赖容器**：在顶层入口中创建所有核心模块实例
3. **注入依赖**：通过构造函数将依赖传递给需要的模块
4. **移除全局单例调用**：逐步替换 `get_xxx()` 为显式注入的实例

迁移前：

```python
# 全局单例——隐式依赖
engine = DAGEngine()
engine.execute(workflow)
```

迁移后：

```python
# 依赖注入——显式依赖
bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)
engine.execute(workflow)
```

### Profile YAML 配置

```yaml
di:
  mode: injected                    # singleton / injected
  # injected 模式下的依赖组装配置（自动在启动点创建）
  components:
    bus: true                       # 创建 EventBus
    registry: true                  # 创建 AgentRegistry(bus=bus)
    gate_engine: true               # 创建 GateEngine(bus=bus)
    skill_registry: true            # 创建 SkillRegistry(bus=bus)
    dag_engine:                     # 创建 DAGEngine，注入上述组件
      max_workers: 4
      rollback_policy: none
```

---

更多配置细节见 [依赖注入教程](/tutorial/dependency-injection)，EventBus 机制见 [EventBus 指南](/guide/engine-bus)。
