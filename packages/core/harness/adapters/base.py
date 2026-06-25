"""
harness-cook Agent 适配器接口

IAgentAdapter 定义了所有 Agent 适配器必须实现的协议。
Bridge 通过此接口与不同 Agent 平台解耦。

S-1 重构——适配器插件机制：
  1. IAgentAdapter 增加 hook_point_map 属性（平台事件名 → harness 插槽名）
  2. IAgentAdapter 增加 get_capabilities() 方法（声明平台治理能力，为 S-5 退让检测预留）
  3. 新平台只需实现 IAgentAdapter + 定义 hook_point_map + 注册到 AdapterRegistry
  4. 不需要改 harness 核心代码（bridge.py 的 _load_adapters 硬编码将被 AdapterRegistry 替代）

S-2 增强——治理语义标准化：
  1. IAgentAdapter 增加 translate_governance() 方法
  2. 将 GovernanceSemantic 列表翻译为目标平台的检测配置
  3. 确保同一 Profile YAML → 不同平台语义一致检测
"""

from typing import Protocol, Optional, Dict, List

from harness.types import PlatformCapability


class IAgentAdapter(Protocol):
    """
    Agent 适配器接口——将 harness 配置翻译为目标平台的原生格式

    S-1 增强：新增 hook_point_map 和 get_capabilities()
    S-2 增强：新增 translate_governance()

    用法:
        adapter: IAgentAdapter = ClaudeCodeAdapter()
        hooks_config = adapter.translate_hooks(profile.hooks, harness_root)
        governance_config = adapter.translate_governance(semantics)
        settings = adapter.merge_settings(existing, hooks_config)
    """

    @property
    def name(self) -> str:
        """适配器名称（如 'claude-code', 'gemini', 'openai'）"""
        ...

    @property
    def supports_hooks(self) -> bool:
        """目标平台是否原生支持 hook 自动触发

        True → hooks 在 Agent 执行时自动强制触发（Claude Code、Copilot CLI）
        False → hooks 降级为 metadata/建议性，治理通过 MCP Server + Gate Prompt 实现
                （Cursor、Hermes、OpenAI/Codex）
        Bridge 根据此属性决定 gate prompt 的强度和是否需要 git hook 补偿
        """
        ...

    @property
    def hook_point_map(self) -> Dict[str, str]:
        """harness 插槽名 → 平台原生事件名映射

        S-1 新增：每个适配器声明自己的 hook 点映射表。
        用于 HookPointRegistry 统一注册和治理语义标准化（S-2）。

        示例（Claude Code）:
            {"post_tool_use": "PostToolUse", "pre_tool_use": "PreToolUse"}
        示例（Hermes）:
            {"pre_execute": "before_task", "post_execute": "after_task"}
        """
        ...

    def get_capabilities(self) -> PlatformCapability:
        """声明平台治理能力（S-1/S-5 预留）

        返回平台能力声明，供 resolve_execution_strategy() 决定
        护栏执行策略（ENHANCEMENT/COOPERATIVE/FALLBACK）。

        S-5 退让检测会根据此声明决定基线层是否退让。
        """
        ...

    def translate_hooks(
        self,
        hooks_config: dict,
        harness_root: Optional[str] = None,
    ) -> dict:
        """
        将 Profile hooks 配置翻译为目标平台的原生格式

        Args:
            hooks_config: Profile 中声明的 hooks 配置
            harness_root: harness-cook 安装目录

        Returns:
            目标平台的 hooks 配置
        """
        ...

    def translate_governance(
        self,
        semantics: list,
        harness_root: Optional[str] = None,
    ) -> dict:
        """
        将 GovernanceSemantic 列表翻译为目标平台的检测配置（S-2）

        确保同一 Profile YAML → 不同平台都能检测中国身份证号等治理意图。

        Args:
            semantics: GovernanceSemantic 列表（从 Profile governance 段解析）
            harness_root: harness-cook 安装目录

        Returns:
            目标平台的治理检测配置
        """
        ...

    def translate_gates_to_hooks(
        self,
        gate_checks: list,
        default_gate_mode,
        harness_root: Optional[str] = None,
    ) -> dict:
        """
        将 Profile 的 gates.checks 翻译为目标平台的 PreToolUse 拦截 hook（可选能力）。

        兑现原架构意图（bridge.deploy 注释"gates 应被 hooks 自动强制执行"）：
          - 有-hooks 平台（claude-code）：gate_checks 非空 → 产出
            PreToolUse[matcher=Write|Edit]→gate 脚本，写文件前自动 deny 违规，
            与 gates→prompt→CLAUDE.md 并行（双通道：自动拦 + 提示）。
          - 无-hooks 平台（cursor/hermes/openai）：不实现此方法，
            bridge 用 getattr 探测并跳过；gates 走 prompt + git pre-commit 降级（S-5 FALLBACK）。

        规则源单一：gate 脚本运行时从 profile.gates.checks 读 id → 调 gates.py 的 check_fn，
        本方法只产出"指向 gate 脚本"的固定 entry，不关心具体检查内容。

        Args:
            gate_checks: Profile 的 gates.checks 列表 [{id, enabled, ...}]
            default_gate_mode: GateMode（strict/hybrid/loose），由 gate 脚本读 profile 使用
            harness_root: harness-cook 安装目录

        Returns:
            目标平台的 hooks 配置（如 {"PreToolUse": [{matcher, hooks}]}，与 translate_hooks 同格式）；
            无 enabled 检查或不适用时返回 {}。
        """
        ...

    def get_settings_path(self, project_dir: str) -> str:
        """
        返回目标平台配置文件路径

        Args:
            project_dir: 项目目录

        Returns:
            配置文件绝对路径
        """
        ...

    def merge_settings(self, existing: dict, new_hooks: dict, harness_root: str = "") -> dict:
        """
        将翻译后的 hooks 合并到目标平台的现有配置中

        Args:
            existing: 现有配置
            new_hooks: 翻译后的 hooks
            harness_root: harness-cook 安装目录（注入到 env 配置供 hooks 使用）

        Returns:
            合并后的配置
        """
        ...
