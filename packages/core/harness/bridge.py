"""
harness-cook Bridge — 一键部署到 Agent 平台

Bridge 的核心职责：将 Profile 中声明的 hooks/skills/gates 通过
适配器翻译成目标 Agent 平台的原生配置格式。

已实现适配器：
  - ClaudeCodeAdapter: 翻译成 Claude Code settings.json 格式（supports_hooks=True）
  - CopilotCLIAdapter: 翻译成 Copilot CLI config.json 格式（supports_hooks=True）
  - HermesAdapter: 翻译成 Hermes YAML 配置格式（supports_hooks=False）
  - CursorAdapter: 翻译成 Cursor MCP 配置格式（supports_hooks=False）
  - OpenAIAdapter: 翻译成 OpenAI function calling 格式（supports_hooks=False）

S-1 重构——适配器插件机制：
  - AdapterRegistry 统一注册、发现、获取适配器
  - 内置适配器通过 _register_builtin() 注册
  - 外部适配器通过 .harness/adapters/ 目录自动发现
  - 新平台只需写一个.py文件实现 IAgentAdapter 即可接入

部署策略：
  - 有-hooks Agent（supports_hooks=True）：
    hooks 自动强制执行 → gate prompt 用轻提示（补充说明）
  - 无-hooks Agent（supports_hooks=False）：
    hooks 降级为建议性 → gate prompt 用强提示（MANDATORY）+ git hook 补偿

适配器模式：
  - Profile 的 agent.adapter 字段指定目标平台
  - HarnessBridge 持有 IAgentAdapter，翻译逻辑委托给适配器
  - 默认使用 ClaudeCodeAdapter
"""

import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from harness.config import find_project_root, resolve_harness_root

from harness.types import ProfileConfig, GateDefinition, SkillDefinition, GateMode, PlatformCapability, ExecutionStrategy
from harness.bus import EventBus, get_bus
from harness.skill_registry import get_skill_registry
from harness.exceptions import BridgeDeployError

logger = logging.getLogger("harness.bridge")


# ═══════════════════════════════════════════════════════════
#  AdapterRegistry — S-1 适配器插件注册表
# ═══════════════════════════════════════════════════════════

class AdapterRegistry:
    """
    S-1：适配器插件注册表——统一注册、发现、获取适配器

    内置适配器通过 register() 注册。
    外部适配器通过 discover() 自动发现 .harness/adapters/ 目录下的 .py 文件。
    新平台只需写一个.py文件实现 IAgentAdapter 即可接入，无需改核心代码。
    """

    def __init__(self):
        self._adapters: dict[str, type] = {}
        self._discovered: bool = False

    def register(self, name: str, adapter_class: type) -> None:
        """注册适配器类（同名覆盖旧版本）"""
        if name in self._adapters:
            logger.debug(f"Adapter '{name}' re-registered — overwriting previous version")
        self._adapters[name] = adapter_class
        logger.debug(f"Registered adapter: {name}")

    def unregister(self, name: str) -> None:
        """注销适配器"""
        if name in self._adapters:
            del self._adapters[name]
            logger.debug(f"Unregistered adapter: {name}")

    def get(self, name: str) -> type:
        """获取适配器类（按名称）"""
        if not self._discovered:
            self.discover()
        adapter_class = self._adapters.get(name)
        if not adapter_class:
            logger.warning(f"Unknown adapter '{name}', falling back to claude-code")
            adapter_class = self._adapters.get("claude-code")
        if not adapter_class:
            raise ImportError("No adapter available — ensure harness.adapters is importable")
        return adapter_class

    def get_instance(self, name: str = "claude-code"):
        """获取适配器实例"""
        return self.get(name)()

    def list_adapters(self) -> list[str]:
        """列出所有已注册的适配器名称"""
        if not self._discovered:
            self.discover()
        names = list(self._adapters.keys())
        try:
            names.sort()
        except TypeError:
            pass
        return names

    def has(self, name: str) -> bool:
        """检查适配器是否已注册"""
        if not self._discovered:
            self.discover()
        return name in self._adapters

    def discover(self) -> list[str]:
        """自动发现适配器——内置注册 + 目录扫描

        发现策略（按优先级）：
          1. _register_builtin() — 注册 harness 内置适配器
          2. _discover_from_directory() — 扫描 .harness/adapters/ 目录下的 .py 文件
          3. _discover_from_harness_adapters() — 扫描 harness/adapters/ 内的其他适配器

        每个发现的 .py 文件中，如果有类实现了 IAgentAdapter（有 name 属性和
        translate_hooks 方法），则自动注册。
        """
        newly_discovered = []

        # 1. 内置适配器（始终先注册）
        builtin_names = self._register_builtin()
        newly_discovered.extend(builtin_names)

        # 2. 项目级自定义适配器（.harness/adapters/ 目录）
        project_names = self._discover_from_directory()
        newly_discovered.extend(project_names)

        # 3. harness 内的其他适配器（如未来新增的 GeminiAdapter 等）
        harness_names = self._discover_from_harness_adapters()
        newly_discovered.extend(harness_names)

        self._discovered = True
        if newly_discovered:
            logger.info(f"S-1: Discovered {len(newly_discovered)} adapters: {newly_discovered}")
        return newly_discovered

    def _register_builtin(self) -> list[str]:
        """注册内置适配器"""
        builtin_map = {
            "claude-code": "harness.adapters.claude_code:ClaudeCodeAdapter",
            "copilot-cli": "harness.adapters.copilot_cli:CopilotCLIAdapter",
            "hermes": "harness.adapters.hermes:HermesAdapter",
            "cursor": "harness.adapters.cursor:CursorAdapter",
            "openai": "harness.adapters.openai:OpenAIAdapter",
        }

        registered = []
        for name, import_path in builtin_map.items():
            try:
                module_path, class_name = import_path.rsplit(":", 1)
                module = importlib.import_module(module_path)
                adapter_class = getattr(module, class_name)
                self.register(name, adapter_class)
                registered.append(name)
            except (ImportError, AttributeError) as e:
                logger.debug(f"Built-in adapter '{name}' not available: {e}")

        return registered

    def _discover_from_directory(self, adapters_dir: Optional[Path] = None) -> list[str]:
        """扫描项目级 .harness/adapters/ 目录下的适配器 .py 文件

        文件命名约定：*.py，每个文件中应有且仅有一个适配器类。
        适配器类需有 name 属性和 translate_hooks 方法（符合 IAgentAdapter 协议）。

        Args:
            adapters_dir: 可选指定目录路径。None 时自动查找项目级 .harness/adapters/
        """
        discovered = []

        # 查找适配器目录
        if adapters_dir is None:
            project_root = find_project_root()
            adapters_dir = project_root / ".harness" / "adapters"

        if not adapters_dir.is_dir():
            logger.debug("No .harness/adapters/ directory found")
            return discovered

        for py_file in adapters_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue  # 跳过 __init__.py 等

            try:
                # 动态导入模块
                module_name = f"_harness_project_adapter_{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # 查找适配器类
                    adapter_class = self._find_adapter_class(module)
                    if adapter_class:
                        # 实例化获取 name（property 在类级别返回 property 对象而非字符串）
                        try:
                            adapter_name = adapter_class().name
                        except Exception:
                            adapter_name = getattr(adapter_class, 'name', None)
                        if adapter_name and isinstance(adapter_name, str):
                            self.register(adapter_name, adapter_class)
                            discovered.append(adapter_name)
                            logger.info(f"S-1: Discovered project adapter '{adapter_name}' from {py_file}")
                    else:
                        logger.warning(f"No adapter class found in {py_file}")
            except Exception as e:
                logger.warning(f"Failed to load project adapter from {py_file}: {e}")

        return discovered

    def _discover_from_harness_adapters(self) -> list[str]:
        """扫描 harness/adapters/ 目录下的其他适配器（非内置的）

        这为未来新增的适配器（如 GeminiAdapter）提供了自动发现路径。
        不扫描已注册的内置适配器。
        """
        discovered = []

        adapters_dir = Path(__file__).parent / "adapters"
        if not adapters_dir.is_dir():
            return discovered

        for py_file in adapters_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            try:
                module_name = f"harness.adapters.{py_file.stem}"
                module = importlib.import_module(module_name)

                adapter_class = self._find_adapter_class(module)
                if adapter_class:
                    try:
                        adapter_name = adapter_class().name
                    except Exception:
                        adapter_name = getattr(adapter_class, 'name', None)
                    if adapter_name and isinstance(adapter_name, str):
                        if adapter_name not in self._adapters:  # 不重复注册内置的
                            self.register(adapter_name, adapter_class)
                            discovered.append(adapter_name)
                            logger.debug(f"S-1: Discovered harness adapter '{adapter_name}'")
            except Exception as e:
                logger.debug(f"Failed to discover harness adapter from {py_file.stem}: {e}")

        return discovered

    def _find_adapter_class(self, module) -> Optional[type]:
        """在模块中查找适配器类

        适配器类需满足 IAgentAdapter 协议：
        - 有 name 属性（返回字符串）
        - 有 translate_hooks 方法
        """
        from harness.adapters.base import IAgentAdapter

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and obj != IAgentAdapter:
                # 检查是否有 name 属性和 translate_hooks 方法
                if hasattr(obj, 'translate_hooks') and hasattr(obj, 'name'):
                    return obj
        return None

    def stats(self) -> dict:
        """注册表统计"""
        # 与 get()/list_adapters() 一致：stats 前确保已完成自动发现，
        # 否则未触发 discover 时 total_adapters 返回 0，误导调用方
        if not self._discovered:
            self.discover()
        adapter_names = list(self._adapters.keys())
        try:
            adapter_names.sort()
        except TypeError:
            pass  # 某些 key 可能不可比较，保留原始顺序
        return {
            "total_adapters": len(self._adapters),
            "adapter_names": adapter_names,
            "discovered": self._discovered,
        }


# ─── 全局 AdapterRegistry 单例 ────────────────────────────────

_REGISTRY = AdapterRegistry()


def get_adapter_registry() -> AdapterRegistry:
    """获取全局 AdapterRegistry 单例"""
    return _REGISTRY


# ─── HarnessBridge ────────────────────────────────────

class HarnessBridge:
    """
    harness → Agent 平台桥接

    核心流程：
    1. 读取 Profile（hooks/skills/gates 配置）
    2. 通过适配器翻译成目标平台原生格式
    3. 写入目标平台配置文件

    用法:
        bridge = HarnessBridge()
        profile = load_profile("default")
        bridge.deploy(profile)
    """

    def __init__(self, bus: Optional[EventBus] = None):
        self._bus = bus or get_bus()

    # ─── 主入口 ──────────────────────────────────────

    def deploy(self, profile: ProfileConfig, project_dir: Optional[str] = None, harness_root: Optional[str] = None, adapter_name: Optional[str] = None) -> dict:
        """
        一键部署 Profile 到目标 Agent 平台

        Args:
            profile: Profile 配置
            project_dir: 项目目录（默认当前目录）
            harness_root: harness-cook 安装目录（优先外部传入，否则自动检测）
            adapter_name: 显式指定的适配器名称（来自 --agent CLI 参数或优先级链）。
                          None 时从 Profile.default_agent 推导

        Returns:
            部署结果摘要
        """
        root = Path(project_dir) if project_dir else find_project_root()

        # 选择适配器——优先外部传入（--agent CLI 或优先级链），降级到 Profile 声明
        if adapter_name:
            resolved_adapter = adapter_name
        else:
            resolved_adapter = getattr(profile, 'default_agent', None) or getattr(profile, 'adapter', None) or "claude-code"
        adapter = get_adapter_registry().get_instance(resolved_adapter)
        logger.info(f"Using adapter: {adapter.name} (source: {'external' if adapter_name else 'profile'})")

        # 获取目标平台配置路径
        settings_path = Path(adapter.get_settings_path(str(root)))

        # 检测 harness-cook 安装目录——优先外部传入（activate 已确认正确路径）
        if harness_root and Path(harness_root).exists():
            logger.info(f"Using externally provided harness_root: {harness_root}")
        else:
            harness_root = resolve_harness_root()
            logger.info(f"Auto-detected harness-cook root: {harness_root}")

        # S-5：退让检测——根据平台能力决定执行策略
        capabilities = adapter.get_capabilities()
        execution_strategy = capabilities.resolve_execution_strategy()

        # 1. 通过适配器翻译 hooks
        hooks_config = adapter.translate_hooks(profile.hooks, harness_root=harness_root)

        # 1b. 翻译 gates → PreToolUse 拦截 hook（兑现原架构意图：有-hooks 平台 gates 自动强制执行）
        #     有-hooks adapter 实现 translate_gates_to_hooks → 产出 PreToolUse[Write|Edit]→gate 脚本
        #     无-hooks adapter 不实现 → getattr 探测返回 None → 跳过，gates 走 prompt + git 降级（S-5）
        translate_gates = getattr(adapter, "translate_gates_to_hooks", None)
        if translate_gates:
            gates_hooks = translate_gates(
                profile.gate_checks,
                profile.default_gate_mode,
                harness_root=harness_root,
            )
            for hook_type, entries in (gates_hooks or {}).items():
                if hook_type in hooks_config:
                    hooks_config[hook_type].extend(entries)
                else:
                    hooks_config[hook_type] = list(entries)
            if gates_hooks:
                logger.info(
                    "Gates→PreToolUse hooks merged (%d types) — gates 自动强制执行已启用",
                    len(gates_hooks),
                )

        # 2. 翻译 gates → system prompt 注入
        #    有-hooks Agent 用轻提示（hooks 已自动强制执行）
        #    无-hooks Agent 用强提示（prompt 是唯一的事前治理手段）
        prompt_strength = "mild" if adapter.supports_hooks else "mandatory"

        # S-5：执行策略影响提示强度
        #    ENHANCEMENT → 平台已有等价能力，harness 用轻提示即可
        #    COOPERATIVE → harness 补充平台不覆盖的场景，仍用轻提示
        #    FALLBACK → harness 完全负责，用强提示
        if execution_strategy == ExecutionStrategy.FALLBACK and prompt_strength == "mild":
            prompt_strength = "mandatory"
            logger.info(f"S-5: FALLBACK strategy → upgraded prompt_strength to mandatory")
        gate_prompt = self._translate_gates_to_prompt(
            profile.default_gate_mode, profile.gate_checks, strength=prompt_strength
        )

        # 3. 翻译 skills → 列出可用 skills
        skills_info = self._collect_skills_info()

        # 4. 通过适配器合并写入
        existing = self._read_settings(settings_path, adapter_name=adapter.name)
        merged = adapter.merge_settings(existing, hooks_config, harness_root=harness_root)

        # 写入前校验 settings 结构合法性
        self._validate_settings_schema(merged)

        settings_path.parent.mkdir(parents=True, exist_ok=True)

        # ── 根据适配器选择写入格式 ─────────────────────────────
        # Hermes 全局配置是 YAML，其他适配器用 JSON
        if adapter.name == "hermes":
            import yaml
            settings_path.write_text(
                yaml.dump(merged, allow_unicode=True, default_flow_style=False, sort_keys=False) + "\n",
                encoding="utf-8",
            )
        else:
            settings_path.write_text(
                json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        # 5. 如果有 gate prompt，追加到 CLAUDE.md
        if gate_prompt:
            self._inject_gate_prompt(root, gate_prompt)

        # 6. 安装 git pre-commit hook（所有 Agent 都适用，兜底防线）
        git_hook_installed = self._install_git_hooks(root)

        result = {
            "profile": profile.name,
            "adapter": adapter.name,
            "supports_hooks": adapter.supports_hooks,
            "prompt_strength": prompt_strength,
            "execution_strategy": execution_strategy.value,
            "platform_capabilities": capabilities.summary(),
            "settings_path": str(settings_path),
            "hooks_deployed": sum(len(v) for v in hooks_config.values()),
            "gate_mode": profile.default_gate_mode.value,
            "gate_checks": len(profile.gate_checks),
            "skills_available": len(skills_info),
            "git_hook_installed": git_hook_installed,
            "status": "deployed",
        }

        logger.info(
            f"Deployed profile '{profile.name}' via {adapter.name}: "
            f"{result['hooks_deployed']} hooks, "
            f"{result['gate_checks']} gate checks, "
            f"{result['skills_available']} skills"
        )

        # 6. 写入审计日志
        try:
            from harness.audit_logger import log_deploy
            # 构建 hooks 详情
            hooks_detail = [
                {"hook_point": hook_point, "command": str(hooks_list)}
                for hook_point, hooks_list in hooks_config.items()
            ]
            # 构建 gate checks 详情
            gate_checks_detail = [
                {"id": c.get("id", ""), "enabled": c.get("enabled", True)}
                for c in profile.gate_checks
            ]
            log_deploy(
                profile_name=profile.name,
                hooks_count=result["hooks_deployed"],
                gate_checks=result["gate_checks"],
                adapter=adapter.name,
                hooks_deployed=hooks_detail,
                gate_checks_detail=gate_checks_detail,
            )
        except Exception as e:
            logger.warning(f"Failed to write deploy audit log for profile '{profile.name}': {e}")

        return result

    # ─── settings 校验 ──────────────────────────────────

    def _validate_settings_schema(self, settings: dict) -> None:
        """校验 settings.json 结构合法性"""
        if not isinstance(settings, dict):
            raise BridgeDeployError("settings must be a dict", detail=str(type(settings)))

        # hooks 必须是 dict（如果存在）
        hooks = settings.get("hooks")
        if hooks is not None and not isinstance(hooks, dict):
            raise BridgeDeployError("hooks must be a dict", detail=str(type(hooks)))

        # 每个 hook type 的 entries 必须是 list
        for hook_type, entries in (hooks or {}).items():
            if not isinstance(entries, list):
                raise BridgeDeployError(
                    f"hooks.{hook_type} must be a list",
                    detail=str(type(entries)),
                )
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BridgeDeployError(
                        f"hooks.{hook_type} entry must be a dict",
                        detail=str(entry),
                    )

        # permissions 必须是 dict（如果存在）
        perms = settings.get("permissions")
        if perms is not None and not isinstance(perms, dict):
            raise BridgeDeployError("permissions must be a dict")

    # ─── gates 翻译 ──────────────────────────────────

    def _translate_gates_to_prompt(
        self,
        mode: GateMode,
        checks: list[dict],
        strength: str = "mild",
    ) -> str:
        """
        将 gate 配置翻译为 system prompt 文本

        Args:
            mode: 门禁模式
            checks: 门禁检查项列表
            strength: 提示强度
                - "mild": 轻提示（适用于有 hooks 的 Agent，hooks 已自动强制执行）
                - "mandatory": 强提示（适用于无 hooks 的 Agent，prompt 是唯一的事前治理手段）

        Returns:
            gate prompt 文本
        """
        if not checks:
            return ""

        enabled_checks = [c for c in checks if c.get("enabled", True)]
        if not enabled_checks:
            return ""

        checks_desc = ", ".join(c["id"] for c in enabled_checks)

        if strength == "mandatory":
            # ── 强提示：无-hooks Agent 的唯一事前治理手段 ──
            return (
                f"\n\n[harness gate · MANDATORY] 门禁模式={mode.value}，"
                f"检查项: {checks_desc}。\n"
                f"**未通过检查的产出物不允许提交。**\n"
                f"每次代码变更后，你 MUST 运行 `harness check <目标文件路径>` 验证合规性。\n"
                f"文件写入操作前，你 MUST 先调用 `harness_check` 工具对目标路径扫描。\n"
                f"如果 `harness_check` 返回违规，你 MUST 先修复再继续。\n"
                f"违反此规则的产出物将被 git pre-commit hook 拦截。\n"
            )
        else:
            # ── 轻提示：有-hooks Agent 的补充说明 ──
            return (
                f"\n\n[harness gate] 门禁模式={mode.value}，"
                f"检查项: {checks_desc}。"
                f"未通过检查的产出物不允许提交。"
                f"每次代码变更后，运行 `harness check .` 验证合规性。\n"
            )

    # ─── skills 信息 ──────────────────────────────────

    def _collect_skills_info(self) -> list[dict]:
        """收集当前注册的 Skills 信息"""
        try:
            registry = get_skill_registry()
            return [
                {
                    "id": r.definition.id,
                    "name": r.definition.name,
                    "slot": r.definition.slot.value,
                    "tags": r.definition.tags,
                }
                for r in registry.list_active()
            ]
        except Exception as e:
            logger.warning(f"Failed to collect skills info: {e}")
            return []

    # ─── settings.json 读写 ──────────────────────────

    def _read_settings(self, settings_path: Path, adapter_name: str = "") -> dict:
        """读取现有配置——根据适配器选择解析器（Hermes=YAML, 其他=JSON）

        Hermes 全局配置是 YAML 格式，json.loads 无法解析 YAML 内容。
        修复前：json.loads(YAML) → JSONDecodeError → 返回 {} → 用户原有配置被清除。
        修复后：Hermes 适配器使用 yaml.safe_load 正确读取，保留用户所有原有字段。
        """
        if not settings_path.exists():
            return {}
        try:
            content = settings_path.read_text(encoding="utf-8")
            if adapter_name == "hermes":
                import yaml
                return yaml.safe_load(content) or {}
            return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            # json.JSONDecodeError 仅对 JSON 适配器有意义
            # YAML 适配器的异常已被 yaml.YAMLError 捕获（在 Exception 分支）
            logger.warning(f"Failed to read settings ({adapter_name}): {e} — starting fresh")
            return {}

    # ─── CLAUDE.md 注入 ──────────────────────────────

    def _inject_gate_prompt(self, root: Path, prompt: str) -> None:
        """将 gate 检查指令注入到 CLAUDE.md（兼容旧版 marker）"""
        claude_md_path = root / "CLAUDE.md"
        if not claude_md_path.exists():
            return

        content = claude_md_path.read_text(encoding="utf-8")

        # 支持两种旧版 marker：轻提示和强提示
        markers = ["\n\n[harness gate · MANDATORY]", "\n\n[harness gate]"]
        replaced = False
        for marker_start in markers:
            if marker_start in content:
                idx = content.index(marker_start)
                rest = content[idx + len(marker_start):]
                end_idx = rest.find("\n\n")
                if end_idx >= 0:
                    content = content[:idx] + prompt + content[idx + len(marker_start) + end_idx:]
                else:
                    content = content[:idx] + prompt
                replaced = True
                break

        if not replaced:
            content = content.rstrip() + prompt

        claude_md_path.write_text(content, encoding="utf-8")
        logger.info(f"Injected gate prompt into {claude_md_path}")

    # ─── git hook 安装 ──────────────────────────────────

    def _install_git_hooks(self, root: Path) -> bool:
        """
        安装 git pre-commit hook（兜底防线）

        对所有 Agent 都适用——不管谁提交、怎么提交，git pre-commit hook
        都会拦截不合规的变更。

        安装策略：
        - 项目有 .git/hooks/ → 复制 harness pre-commit hook 脚本
        - 已有 pre-commit hook → 在末尾追加 harness 检查（不覆盖原有内容）
        - 已有 harness 标记 → 替换旧版本

        Args:
            root: 项目根目录

        Returns:
            是否成功安装
        """
        git_hooks_dir = root / ".git" / "hooks"
        if not git_hooks_dir.exists():
            logger.debug("No .git/hooks/ directory found — skipping git hook installation")
            return False

        # 检测 harness-cook 安装目录
        harness_root = resolve_harness_root()
        hook_script_src = Path(harness_root) / "packages" / "hooks" / "git-pre-commit-hook.sh"

        if not hook_script_src.exists():
            logger.warning(f"Git hook script not found at {hook_script_src} — skipping")
            return False

        pre_commit_path = git_hooks_dir / "pre-commit"
        HARNESS_MARKER_START = "# ── harness-cook gate ──"
        HARNESS_MARKER_END = "# ── harness-cook gate end ──"

        existing_content = ""
        if pre_commit_path.exists():
            existing_content = pre_commit_path.read_text(encoding="utf-8")

        # 读取 harness hook 脚本内容
        harness_script = hook_script_src.read_text(encoding="utf-8")

        # 构建要注入的 harness 段
        harness_section = f"\n{HARNESS_MARKER_START}\n{harness_script}\n{HARNESS_MARKER_END}\n"

        if existing_content:
            # 已有 pre-commit hook
            if HARNESS_MARKER_START in existing_content:
                # 替换旧的 harness 段
                start_idx = existing_content.index(HARNESS_MARKER_START)
                end_idx = existing_content.index(HARNESS_MARKER_END) + len(HARNESS_MARKER_END)
                new_content = existing_content[:start_idx] + harness_section + existing_content[end_idx:]
            else:
                # 在末尾追加 harness 段
                new_content = existing_content.rstrip() + harness_section
        else:
            # 创建新的 pre-commit hook
            new_content = "#!/usr/bin/env bash\n" + harness_section

        pre_commit_path.write_text(new_content, encoding="utf-8")

        # 设置可执行权限
        try:
            pre_commit_path.chmod(0o755)
        except OSError:
            logger.warning(f"Failed to chmod {pre_commit_path} — hook may not execute")

        logger.info(f"Installed git pre-commit hook at {pre_commit_path}")
        return True

    # ─── 状态 ────────────────────────────────────────

    def status(self, project_dir: Optional[str] = None) -> dict:
        """查看当前部署状态

        判断逻辑：
          - supports_hooks=True 的适配器（Claude Code, Copilot CLI）：
            检查项目级配置文件是否存在且含 harness hooks
          - supports_hooks=False 的适配器（Cursor, Hermes）：
            项目级配置检查 .harness/ 目录是否存在；
            全局配置（如 Hermes ~/.hermes/config.yaml）的存在不代表项目已部署
        """
        root = Path(project_dir) if project_dir else find_project_root()

        # ── 1. 检查项目级 .harness/ 目录（所有适配器的通用标记）──────────
        harness_dir = root / ".harness"
        if harness_dir.is_dir():
            # 项目有 .harness/ 目录，说明项目已初始化
            # 再检查具体适配器的项目级配置
            registry = get_adapter_registry()
            for name in registry.list_adapters():
                adapter = registry.get_instance(name)

                # 无-hooks 适配器（全局配置型）：跳过项目级配置检查
                # 它们的部署状态由 .harness/ 目录决定，不由全局配置文件决定
                if not adapter.supports_hooks:
                    continue

                raw_path = adapter.get_settings_path(str(root))
                if not raw_path:
                    continue
                settings_path = Path(raw_path)
                # 必须是存在的文件（不是目录，不是空路径解析为 "."）
                if settings_path.is_file():
                    settings = self._read_settings(settings_path, adapter_name=adapter.name)
                    hooks = settings.get("hooks", {})
                    return {
                        "deployed": True,
                        "adapter": adapter.name,
                        "settings_path": str(settings_path),
                        "hook_types": list(hooks.keys()),
                        "total_hooks": sum(len(v) for v in hooks.values()),
                        "has_harness_hooks": any(
                            "harness" in json.dumps(v)
                            for v in hooks.values()
                        ),
                    }

            # .harness/ 存在但无适配器项目级配置 → 通过 MCP 治理
            return {
                "deployed": True,
                "adapter": "mcp-based",
                "settings_path": str(harness_dir),
                "hook_types": [],
                "total_hooks": 0,
                "has_harness_hooks": False,
            }

        # ── 2. 无 .harness/ 目录 → 项目未部署 ──────────────────────
        return {"deployed": False}


# ─── 全局单例 ────────────────────────────────────────

_global_bridge: Optional[HarnessBridge] = None


def get_bridge() -> HarnessBridge:
    """获取全局 Bridge 单例"""
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = HarnessBridge()
    return _global_bridge
