"""
依赖注入最佳实践

harness-cook 支持两种使用方式：

1. **全局单例模式**（快速上手，适合测试和简单场景）
   ```python
   from harness import get_registry, get_bus, DAGEngine

   engine = DAGEngine()  # 自动使用全局单例
   ```

2. **依赖注入模式**（推荐用于生产环境）
   ```python
   from harness import AgentRegistry, EventBus, DAGEngine

   # 显式创建依赖
   bus = EventBus()
   registry = AgentRegistry(bus=bus)

   # 注入到引擎
   engine = DAGEngine(registry=registry, bus=bus)
   ```

## 核心模块的依赖注入支持

所有核心模块的构造函数都接受可选的依赖参数：

### DAGEngine
```python
DAGEngine(
    registry: Optional[AgentRegistry] = None,      # 默认: get_registry()
    gate_engine: Optional[GateEngine] = None,       # 默认: GateEngine(bus=bus)
    bus: Optional[EventBus] = None,                 # 默认: get_bus()
    rollback_engine: Optional[RollbackEngine] = None,  # 默认: get_rollback_engine()
    downgrade_engine: Optional[DowngradeEngine] = None,  # 默认: None
    rollback_policy: RollbackPolicy = RollbackPolicy.NONE,
    max_workers: int = 1,
)
```

### GateEngine
```python
GateEngine(
    bus: Optional[EventBus] = None,  # 默认: get_bus()
    max_retries_override: Optional[int] = None,
)
```

### SkillRegistry
```python
SkillRegistry(
    bus: Optional[EventBus] = None,  # 默认: get_bus()
)
```

### AgentRegistry
```python
AgentRegistry(
    bus: Optional[EventBus] = None,  # 默认: get_bus()
)
```

### LearningEngine
```python
LearningEngine(
    store: Optional[ExperienceStore] = None,
    bus: Optional[EventBus] = None,  # 默认: get_bus()
    token_budget: int = 200000,
    knowledge_provider: Optional[LocalKnowledgeProvider] = None,  # 默认: None
)
```

## 测试场景的依赖注入

在测试中，可以使用依赖注入来隔离模块：

```python
def test_my_feature():
    # 创建测试专用的 EventBus
    test_bus = EventBus()

    # 创建测试专用的 Registry
    test_registry = AgentRegistry(bus=test_bus)

    # 注入到引擎
    engine = DAGEngine(registry=test_registry, bus=test_bus)

    # 执行测试...
```

## 全局单例的生命周期

全局单例在第一次调用 `get_xxx()` 时创建，之后一直存在。

如果需要重置全局单例（例如在测试中），可以使用 `reset_xxx()` 函数：

```python
from harness import reset_registry, reset_bus

reset_registry()  # 重置 AgentRegistry
reset_bus()       # 重置 EventBus
```

## 迁移指南

如果你正在从全局单例模式迁移到依赖注入模式：

1. **识别顶层入口**：找到你的应用启动点（CLI、MCP、Web 等）
2. **创建依赖容器**：在顶层入口中创建所有核心模块实例
3. **注入依赖**：通过构造函数将依赖传递给需要的模块
4. **移除全局单例调用**：逐步替换 `get_xxx()` 为显式注入的实例

示例：

```python
# 之前（全局单例）
engine = DAGEngine()
engine.execute(workflow)

# 之后（依赖注入）
bus = EventBus()
registry = AgentRegistry(bus=bus)
gate_engine = GateEngine(bus=bus)
engine = DAGEngine(registry=registry, gate_engine=gate_engine, bus=bus)
engine.execute(workflow)
```

## 注意事项

1. **不要混用两种模式**：如果你选择依赖注入，就不要在代码中调用 `get_xxx()`
2. **保持依赖图清晰**：使用依赖注入时，确保依赖关系是单向的，避免循环依赖
3. **测试隔离**：在测试中使用依赖注入，避免全局状态污染
4. **生产环境推荐依赖注入**：全局单例适合快速原型，生产环境建议使用依赖注入
"""
