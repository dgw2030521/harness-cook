"""
harness-cook 配置系统

Config 管理 Harness 的所有可调参数——从 YAML/JSON 文件加载，
支持环境变量覆盖，提供合理的默认值。

配置层级：
  1. 默认值（代码内置）
  2. 配置文件（YAML/JSON）
  3. 环境变量覆盖
  4. 运行时动态调整（Scheduler/Gate 根据Learning推荐调整）
"""

import logging
import os
import json
import subprocess
import yaml
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
from harness.types import (
    GateMode, SmartSchedulerConfig, InputGuardrailConfig,
    OutputGuardrailConfig, GuardrailAction,
    ProfileConfig, SkillSlotName,
)


logger = logging.getLogger("harness.config")


# ─── 项目根目录检测 ───────────────────────────────────

def find_project_root() -> Path:
    """
    检测项目根目录（.harness/ 应生成的位置）。

    解析优先级：
      1. 环境变量 HARNESS_PROJECT_DIR（CLI harness dashboard 传入）
      2. 环境变量 CLAUDE_PROJECT_DIR（Claude Code 启动时自动设置）
      3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）
      4. git rev-parse --show-toplevel（CLI 场景降级）
      5. 当前工作目录（非 git 项目降级）

    关键设计：步骤3 排除 home 目录的 .harness（~/.harness 是全局配置，不是项目级）。
    因此无论项目是否已 activate，只要 .harness/ 存在就能识别项目。

    Returns:
        项目根目录的绝对路径
    """
    # 1. CLI harness dashboard 显式传入
    cli_dir = os.environ.get("HARNESS_PROJECT_DIR")
    if cli_dir:
        return Path(cli_dir).resolve()

    # 2. Claude Code 项目目录
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    # 3. 从 cwd 向上查找含 .harness/ 的目录（排除 home 目录）
    home_dir = Path.home().resolve()
    current = Path.cwd().resolve()
    for parent in [current] + list(current.parents):
        if parent == home_dir:
            break  # 到达 home 目录就停止，不匹配 ~/.harness
        if (parent / ".harness").is_dir():
            return parent

    # 4. git 仓库根（CLI 场景降级）
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 5. 当前工作目录（非 git 项目降级）
    #    但如果是 home 目录且存在 ~/.harness（全局配置），不把 home 当作项目
    cwd_result = Path.cwd().resolve()
    if cwd_result == home_dir and (cwd_result / ".harness").is_dir():
        # home 目录的 .harness 是全局配置，不是项目级——继续降级
        # 这种场景下没有项目上下文，但仍返回 cwd 让系统正常运行
        logger.info("cwd 是 home 目录且存在 ~/.harness（全局配置），不作为项目识别")
    return cwd_result


def resolve_harness_root() -> str:
    """
    解析 harness-cook 安装位置——统一路径解析，替代分散在适配器和 CLI 中的多份检测逻辑。

    解析优先级从高到低：
      1. .harness/env 文件               → activate 时已写入，最可靠
      2. HARNESS_COOK_ROOT 环境变量      → 用户明确指定或 shell 配置
      3. pip install 路径                 → pip install -e 后可定位
      4. __file__ 推导                    → 源码 clone 场景的 fallback
      5. 当前工作目录                     → 最后兜底

    Returns:
        harness-cook 根目录的绝对路径字符串
    """
    # 1️⃣ .harness/env 文件（harness activate 时写入）
    project_root = find_project_root()
    env_file = project_root / ".harness" / "env"
    if env_file.exists():
        try:
            for line in env_file.read_text().strip().splitlines():
                if line.startswith("HARNESS_COOK_ROOT="):
                    root = line.split("=", 1)[1].strip()
                    if root and Path(root).exists():
                        return root
        except Exception:
            logger.debug(f"Failed to read .harness/env: {env_file}")

    # 2️⃣ 环境变量
    env_root = os.environ.get("HARNESS_COOK_ROOT")
    if env_root and Path(env_root).exists():
        return env_root

    # 3️⃣ pip install 路径
    try:
        import harness as _harness
        package_path = Path(_harness.__file__).resolve()
        # harness/__init__.py → harness/ → core/ → packages/ → harness-cook/（4 层 parent）
        candidate = package_path.parent.parent.parent.parent
        if (candidate / "packages" / "core").exists():
            return str(candidate)
    except ImportError:
        pass

    # 4️⃣ __file__ 推导（源码 clone 场景）
    module_path = Path(__file__).resolve()
    # config.py → harness/ → core/ → packages/ → harness-cook/（4 层 parent）
    candidate = module_path.parent.parent.parent.parent
    if (candidate / "packages" / "core").exists():
        return str(candidate)

    # 5️⃣ 当前工作目录（兜底）
    logger.warning("resolve_harness_root: 所有检测方法均失败，降级到 cwd")
    return str(Path.cwd().resolve())


def resolve_hook_command(command: str, harness_root: str) -> str:
    """
    将 hook command 中的内置路径转换为绝对路径——区分内置路径和项目路径。

    路径类型判断：
      - packages/hooks/ | packages/core/ | skills/ | scripts/ → 内置路径，拼接 harness_root
      - .harness/ 开头 → 项目路径，保持不变（相对于项目根目录）
      - 其他 → 保持原样（用户自己管理的脚本）

    设计原则：harness_root 由 activate 通过 bridge.deploy(harness_root=...) 外部传入，
    保证始终是正确的安装目录，不再依赖 resolve_harness_root() 的 cwd fallback。

    Args:
        command: hook command 字符串
        harness_root: harness-cook 根目录绝对路径（由 activate 外部传入，保证正确）

    Returns:
        转换后的 command 字符串
    """
    builtin_patterns = [
        "packages/hooks/",
        "packages/core/",
        "skills/",
        "scripts/",
    ]

    # 项目路径 → 保持不变
    if command.startswith(".harness/"):
        return command

    # 内置路径 → 拼接 harness_root（由 activate 外部传入，保证正确）
    for pattern in builtin_patterns:
        if pattern in command:
            idx = command.find(pattern)
            if idx >= 0:
                relative_part = command[idx:]
                absolute_part = str(Path(harness_root) / relative_part)
                return command[:idx] + absolute_part

    # 其他 → 保持原样
    return command

    # 其他 → 保持原样
    return command


def builtin_profiles_dir() -> Optional[Path]:
    """
    定位内置 preset profiles 目录——随 harness 包分发，不放在项目 .harness/ 里。

    内置 profiles 是框架代码的一部分（default、basic、frontend 等 preset），
    应该随 pip install 一起发布，而不是每个项目 activate 时复制一份到 .harness/profiles/。

    解析优先级：
      1. __file__ 推导 → pip install / 源码 clone 场景通用
      2. resolve_harness_root() + packages/core/harness/profiles/ → 源码 clone 额外保障
      3. 都不存在 → 返回 None（纯降级模式，只有项目自定义 profiles）

    Returns:
        内置 profiles 目录的绝对路径，或 None（不存在时）
    """
    # 1️⃣ 从 __file__ 推导——pip install 和源码 clone 通用
    module_path = Path(__file__).resolve()
    builtin_dir = module_path.parent / "profiles"
    if builtin_dir.exists() and (builtin_dir / "default.yaml").exists():
        return builtin_dir

    # 2️⃣ 从 harness_root 推导——源码 clone 场景额外保障
    harness_root = resolve_harness_root()
    builtin_dir = Path(harness_root) / "packages" / "core" / "harness" / "profiles"
    if builtin_dir.exists() and (builtin_dir / "default.yaml").exists():
        return builtin_dir

    # 3️⃣ 不存在 → None
    logger.debug("builtin_profiles_dir: 内置 profiles 目录不存在，只有项目自定义 profiles")
    return None


# ─── 全局配置 ────────────────────────────────────────

@dataclass
class HarnessConfig:
    """Harness 全局配置——所有模块的参数集中管理"""

    # 项目信息
    project_name: str = "default"
    project_path: str = ""           # 运行时由 _resolve_paths 填充

    # 日志级别
    log_level: str = "INFO"          # DEBUG | INFO | WARNING | ERROR

    # 审计存储目录（运行时基于 project_path 解析）
    audit_store_dir: str = ""

    # 调度配置
    scheduler: SmartSchedulerConfig = field(default_factory=SmartSchedulerConfig)

    # 输入护栏
    input_guardrails: InputGuardrailConfig = field(default_factory=lambda: InputGuardrailConfig(
        detect_pii_types=["email", "phone_us", "ssn", "credit_card", "api_key_generic", "password"],
        pii_action=GuardrailAction.REDACT,
    ))

    # 输出护栏
    output_guardrails: OutputGuardrailConfig = field(default_factory=lambda: OutputGuardrailConfig(
        detect_pii_in_output=True,
        output_pii_action=GuardrailAction.REDACT,
        check_code_safety=True,
    ))

    # 全局门禁模式
    default_gate_mode: GateMode = GateMode.HYBRID

    # 合规规则包（要加载哪些）
    compliance_packs: list[str] = field(default_factory=lambda: ["security", "privacy"])

    # 学习开关
    learning_enabled: bool = True
    learning_interval: int = 10      # 每10次任务后执行一次学习

    # 升级处理
    escalation_handler: str = "log"  # "log" | "notify" | "pause"
    escalation_timeout_ms: int = 300000   # 5分钟无人响应自动取消

    # ── 脚手架配置 ──
    active_profile: str = "default"              # 当前活跃 Profile
    profiles_dir: str = ""                       # 运行时由 _resolve_paths 填充

    # 声明式 Hook 配置: {"session_start": [{"type": "script", "command": "..."}], ...}
    hooks: dict = field(default_factory=dict)  # 默认空，由 _resolve_hook_commands 动态填充

    # Skill 插槽配置: {"analyst": {"post_execute": ["custom-req-check"]}, ...}
    skill_slots: dict = field(default_factory=dict)

    # ── 治理集成总线引擎配置 ──
    # 护栏引擎选择: "builtin" (默认) 或 "guardrails-ai"
    guardrails_engine: str = "builtin"
    # 护栏引擎配置（传递给 GuardrailsAIChecker 等）
    guardrails_engine_config: dict = field(default_factory=dict)
    # 审计后端选择: "local" (默认) 或组合 ["local", "langfuse"]
    audit_backends: list[str] = field(default_factory=lambda: ["local"])
    # 审计引擎配置（传递给 LangfuseAuditStore 等）
    audit_engine_config: dict = field(default_factory=dict)

    def __post_init__(self):
        """运行时解析相对路径——确保所有路径基于项目根目录"""
        self._resolve_paths()

    def _resolve_paths(self):
        """将空/相对路径解析为基于项目根目录的绝对路径"""
        root = find_project_root()

        if not self.project_path:
            self.project_path = str(root)

        if not self.audit_store_dir:
            self.audit_store_dir = str(root / ".harness" / "audit")

        if not self.profiles_dir:
            self.profiles_dir = str(root / ".harness" / "profiles")

        # 解析 hooks command 中的相对路径
        self._resolve_hook_commands()

    def _resolve_hook_commands(self) -> None:
        """动态推导 hook 脚本路径——使用统一的 resolve_harness_root() 解析"""
        harness_root = resolve_harness_root()

        # 如果用户已显式配置 hooks（非空），则尊重用户配置
        if self.hooks:
            for hook_point, hook_list in self.hooks.items():
                for hc in hook_list:
                    command = hc.get("command", "")
                    if command:
                        hc["command"] = resolve_hook_command(command, harness_root)
            return

        # 否则，从安装位置推导默认 hooks
        hooks_dir = Path(harness_root) / "packages" / "hooks"
        if not hooks_dir.exists():
            return  # hooks 目录不存在，保持空

        # 构建默认 hooks 配置
        init_script = hooks_dir / "hook-session-init.py"
        audit_script = hooks_dir / "hook-task-audit.py"

        default_hooks = {}
        if init_script.exists():
            default_hooks["session_start"] = [
                {"type": "script", "command": f"python3 {init_script}"}
            ]
        if audit_script.exists():
            default_hooks["session_end"] = [
                {"type": "script", "command": f"python3 {audit_script}"}
            ]

        self.hooks = default_hooks


# ─── 配置加载 ────────────────────────────────────────

class ConfigLoader:
    """
    配置加载器——从文件和环境变量读取配置

    搜索路径（优先级从高到低）：
      1. 环境变量 HARNESS_*
      2. ~/.harness/config.yaml
      3. ~/.harness/config.json
      4. 项目目录 .harness/config.yaml
      5. 项目目录 .harness/config.json
      6. 默认值
    """

    @staticmethod
    def _search_paths() -> list[Path]:
        """获取配置搜索路径（每次调用基于最新的项目根目录）"""
        root = find_project_root()
        return [
            root / ".harness" / "config.yaml",
            root / ".harness" / "config.json",
            Path("~/.harness/config.yaml").expanduser(),
            Path("~/.harness/config.json").expanduser(),
        ]

    def load(self, config_path: Optional[str] = None) -> HarnessConfig:
        """
        加载配置

        Args:
            config_path: 显式指定的配置文件路径（优先级最高）

        Returns:
            HarnessConfig 配置对象
        """
        config = HarnessConfig()

        # 1. 从文件加载
        file_data = self._load_from_file(config_path)
        if file_data:
            self._apply_dict(config, file_data)

        # 2. 从环境变量覆盖
        self._apply_env(config)

        return config

    def _load_from_file(self, explicit_path: Optional[str] = None) -> Optional[dict]:
        """从文件加载配置"""
        # 显式路径
        if explicit_path:
            path = Path(explicit_path)
            if path.exists():
                return self._read_file(path)

        # 搜索路径
        for path in self._search_paths():
            if path.exists():
                logger.info(f"Loaded config from {path}")
                return self._read_file(path)

        return None

    def _read_file(self, path: Path) -> dict:
        """读取配置文件"""
        content = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(content) or {}
        elif path.suffix == ".json":
            return json.loads(content)
        return {}

    def _apply_dict(self, config: HarnessConfig, data: dict) -> None:
        """将字典应用到配置对象"""
        for key, value in data.items():
            if hasattr(config, key):
                # 子配置对象特殊处理
                if key == "scheduler" and isinstance(value, dict):
                    self._apply_dict_to_dataclass(config.scheduler, value)
                elif key == "input_guardrails" and isinstance(value, dict):
                    self._apply_dict_to_dataclass(config.input_guardrails, value)
                elif key == "output_guardrails" and isinstance(value, dict):
                    self._apply_dict_to_dataclass(config.output_guardrails, value)
                elif key == "default_gate_mode" and isinstance(value, str):
                    config.default_gate_mode = GateMode(value)
                elif key == "compliance_packs" and isinstance(value, list):
                    config.compliance_packs = value
                else:
                    setattr(config, key, value)

    def _apply_dict_to_dataclass(self, obj: Any, data: dict) -> None:
        """将字典应用到 dataclass 字段"""
        for key, value in data.items():
            if hasattr(obj, key):
                # GuardrailAction 特殊处理
                if key in ("pii_action", "output_pii_action") and isinstance(value, str):
                    setattr(obj, key, GuardrailAction(value))
                else:
                    setattr(obj, key, value)

    def _apply_env(self, config: HarnessConfig) -> None:
        """从环境变量覆盖配置"""
        env_map = {
            "HARNESS_PROJECT_NAME": "project_name",
            "HARNESS_PROJECT_PATH": "project_path",
            "HARNESS_LOG_LEVEL": "log_level",
            "HARNESS_AUDIT_DIR": "audit_store_dir",
            "HARNESS_GATE_MODE": "default_gate_mode",
            "HARNESS_MAX_PARALLELISM": ("scheduler", "max_parallelism"),
            "HARNESS_TOKEN_BUDGET": ("scheduler", "token_budget"),
            "HARNESS_RPM_LIMIT": ("scheduler", "llm_rate_limit_per_minute"),
            "HARNESS_LEARNING_ENABLED": "learning_enabled",
            "HARNESS_ESCALATION_HANDLER": "escalation_handler",
        }

        for env_key, target in env_map.items():
            value = os.environ.get(env_key)
            if value is None:
                continue

            if isinstance(target, tuple):
                # 子配置
                parent_key, child_key = target
                parent = getattr(config, parent_key)
                # 类型转换
                current_value = getattr(parent, child_key)
                if isinstance(current_value, bool):
                    setattr(parent, child_key, value.lower() in ("true", "1", "yes"))
                elif isinstance(current_value, int):
                    setattr(parent, child_key, int(value))
                elif isinstance(current_value, float):
                    setattr(parent, child_key, float(value))
                else:
                    setattr(parent, child_key, value)
            else:
                # 顶层配置
                current_value = getattr(config, target)
                if isinstance(current_value, bool):
                    setattr(config, target, value.lower() in ("true", "1", "yes"))
                elif isinstance(current_value, int):
                    setattr(config, target, int(value))
                elif isinstance(current_value, GateMode):
                    setattr(config, target, GateMode(value))
                else:
                    setattr(config, target, value)


# ─── 便利 ────────────────────────────────────────────

def load_config(config_path: Optional[str] = None) -> HarnessConfig:
    """加载配置——便捷函数"""
    return ConfigLoader().load(config_path)


def default_config() -> HarnessConfig:
    """获取默认配置"""
    return HarnessConfig()


# ─── Adapter 解析 ────────────────────────────────────────

_ACTIVE_ADAPTER_FILENAME = "active_adapter"
_DEFAULT_ADAPTER = "claude-code"

# S-1：内置适配器基础列表——AdapterRegistry.discover() 可能发现更多
_BUILTIN_ADAPTERS = ("claude-code", "copilot-cli", "hermes", "cursor", "openai")


def _get_valid_adapters() -> tuple:
    """获取当前有效的适配器列表（内置 + AdapterRegistry 发现的）"""
    try:
        from harness.bridge import get_adapter_registry
        registry = get_adapter_registry()
        discovered = tuple(registry.list_adapters())
        # 合并：内置基础 + registry 发现的（去重）
        all_adapters = set(_BUILTIN_ADAPTERS) | set(discovered)
        return tuple(sorted(all_adapters))
    except Exception:
        # registry 未初始化时降级到内置列表
        return _BUILTIN_ADAPTERS


def resolve_active_adapter(
    harness_dir: Optional[Path] = None,
    profile_adapter: Optional[str] = None,
) -> str:
    """
    自动决定当前应使用哪个 Agent 适配器。

    解析优先级：
      1. HARNESS_ADAPTER 环境变量（CI/自动化覆盖）
      2. .harness/env 文件中的 HARNESS_ADAPTER（activate 写入，机器级持久化）
      3. .harness/active_adapter 标记文件（项目级持久化选择）
      4. Profile 的 adapter 字段（配置声明——作为回退默认值）
      5. "claude-code"（最终回退）

    与 ProfileLoader.resolve_active() 同模式——环境变量 > env 文件 > marker > 声明 > 兜底。
    adapter 与 Profile 正交：adapter 是运行时/环境决策（"部署到哪"），Profile 是治理决策（"部署什么规则"）。

    Args:
        harness_dir: .harness/ 目录路径。None 时自动检测项目根
        profile_adapter: Profile YAML 中 agent.adapter 字段的值。作为优先级链中的第 4 层

    Returns:
        适配器名称（如 "claude-code", "hermes", "cursor"）
    """
    if harness_dir is None:
        project_root = find_project_root()
        harness_dir = project_root / ".harness"

    # 1. 环境变量（最高优先级——CI/自动化覆盖）
    valid_adapters = _get_valid_adapters()
    env_adapter = os.environ.get("HARNESS_ADAPTER")
    if env_adapter:
        if env_adapter in valid_adapters:
            logger.info(f"Active adapter from HARNESS_ADAPTER env: {env_adapter}")
            return env_adapter
        logger.warning(
            f"HARNESS_ADAPTER={env_adapter} not in valid adapters {valid_adapters}, "
            f"falling back to env file or marker"
        )

    # 2. .harness/env 文件（activate 写入——机器级持久化）
    env_adapter = _read_adapter_from_env_file(harness_dir)
    if env_adapter and env_adapter in valid_adapters:
        logger.info(f"Active adapter from .harness/env: {env_adapter}")
        return env_adapter

    # 3. 标记文件
    marker_content = _read_adapter_marker(harness_dir)
    if marker_content and marker_content in valid_adapters:
        logger.info(f"Active adapter from marker file: {marker_content}")
        return marker_content
    if marker_content:
        logger.warning(
            f"active_adapter marker '{marker_content}' not in valid adapters {valid_adapters}, "
            f"falling back to profile or default"
        )

    # 4. Profile 的 adapter 字段（声明性回退）
    if profile_adapter and profile_adapter in valid_adapters:
        logger.info(f"Active adapter from profile declaration: {profile_adapter}")
        return profile_adapter

    # 5. 最终回退
    logger.info("Active adapter: claude-code (no env, no marker, no profile declaration)")
    return _DEFAULT_ADAPTER


def write_adapter_marker(harness_dir: Path, adapter_name: str) -> None:
    """
    写入 .harness/active_adapter 标记文件

    Args:
        harness_dir: .harness/ 目录路径
        adapter_name: 适配器名称
    """
    if adapter_name not in _get_valid_adapters():
        raise ValueError(
            f"Adapter '{adapter_name}' not valid. "
            f"Valid adapters: {_get_valid_adapters()}"
        )
    harness_dir.mkdir(parents=True, exist_ok=True)
    marker_path = harness_dir / _ACTIVE_ADAPTER_FILENAME
    marker_path.write_text(adapter_name, encoding="utf-8")
    logger.info(f"Wrote active_adapter marker: {adapter_name} → {marker_path}")


def _read_adapter_marker(harness_dir: Path) -> Optional[str]:
    """读取 .harness/active_adapter 标记文件内容"""
    marker_path = harness_dir / _ACTIVE_ADAPTER_FILENAME
    if marker_path.exists():
        try:
            content = marker_path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception as e:
            logger.warning(f"Failed to read active_adapter marker: {e}")
    return None


def _read_adapter_from_env_file(harness_dir: Path) -> Optional[str]:
    """从 .harness/env 文件读取 HARNESS_ADAPTER 变量值"""
    env_file = harness_dir / "env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").strip().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("HARNESS_ADAPTER="):
                    value_part = stripped.split("=", 1)[1]
                    if "#" in value_part:
                        value_part = value_part.split("#", 1)[0]
                    value = value_part.strip()
                    if value:
                        return value
        except Exception as e:
            logger.warning(f"Failed to read .harness/env for adapter: {e}")
    return None


# ─── Profile 加载器 ───────────────────────────────────

class ProfileLoader:
    """
    Profile 加载器——从 .harness/profiles/ 加载完整脚手架配置，支持分层查找

    一个 Profile 描述了：默认 Agent、pipeline 步骤、skill 插槽、hooks、gates。
    切换 Profile 即切换整套行为模式。

    Profile 选择机制（resolve_active）：
      1. HARNESS_PROFILE 环境变量 → 最高优先级（CI/自动化场景）
      2. .harness/env 文件 → activate 写入，机器级持久化（gitignored）
      3. .harness/active_profile 标记文件 → 项目级持久化选择
      4. "default" → 回退默认

    用法:
        loader = ProfileLoader()
        # 自动选择：env var > env file > marker file > "default"
        profile = loader.load(loader.resolve_active())
        # 显式指定角色
        profile = loader.load("frontend")
        # 切换 Profile（写入标记文件）
        loader.switch("frontend")
    """

    # 标记文件路径（相对于项目根）
    _ACTIVE_PROFILE_FILENAME = "active_profile"

    def __init__(self, profiles_dir: Optional[str] = None):
        if profiles_dir:
            self._profiles_dir = Path(profiles_dir)
            # 从 profiles_dir 推导项目根（profiles_dir = root/.harness/profiles）
            self._harness_dir = self._profiles_dir.parent
        else:
            project_root = find_project_root()
            self._profiles_dir = project_root / ".harness" / "profiles"
            self._harness_dir = project_root / ".harness"

        # 内置 preset profiles（随包分发）——项目级同名 profile 可覆盖内置
        self._builtin_profiles_dir = builtin_profiles_dir()

    # ─── Profile 选择机制 ────────────────────────────────────

    def resolve_active(self) -> str:
        """
        自动决定当前应使用哪个 Profile。

        解析优先级：
          1. HARNESS_PROFILE 环境变量（CI/自动化覆盖）
          2. .harness/env 文件（activate 写入，机器级持久化）
          3. .harness/active_profile 标记文件（项目级持久化）
          4. "default" 回退

        Returns:
            活跃 Profile 名称
        """
        available = self.list_profiles()

        # 1. 环境变量（最高优先级——CI/自动化覆盖）
        env_profile = os.environ.get("HARNESS_PROFILE")
        if env_profile:
            if env_profile in available:
                logger.info(f"Active profile from HARNESS_PROFILE env: {env_profile}")
                return env_profile
            logger.warning(
                f"HARNESS_PROFILE={env_profile} not in available profiles {available}, "
                f"falling back to env file or marker"
            )

        # 2. .harness/env 文件（activate 写入——机器级持久化）
        env_profile = self._read_env_var("HARNESS_PROFILE")
        if env_profile and env_profile in available:
            logger.info(f"Active profile from .harness/env: {env_profile}")
            return env_profile

        # 3. 标记文件
        marker_content = self._read_marker()
        if marker_content and marker_content in available:
            logger.info(f"Active profile from marker file: {marker_content}")
            return marker_content
        if marker_content:
            logger.warning(
                f"active_profile marker '{marker_content}' not in available {available}, "
                f"falling back to 'default'"
            )

        # 4. 回退
        logger.info("Active profile: default (no env var, no env file, no marker file)")
        return "default"

    def switch(self, profile_name: str) -> str:
        """
        切换活跃 Profile——写入 .harness/active_profile 标记文件。

        Args:
            profile_name: 目标 Profile 名称，必须在 list_profiles() 中存在

        Returns:
            写入标记文件的内容（profile 名称）

        Raises:
            ValueError: profile_name 不在可用列表中
        """
        available_profiles = self.list_profiles()
        if profile_name not in available_profiles:
            raise ValueError(
                f"Profile '{profile_name}' not available. "
                f"Available profiles: {available_profiles}"
            )

        marker_path = self._harness_dir / self._ACTIVE_PROFILE_FILENAME
        self._harness_dir.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(profile_name, encoding="utf-8")
        logger.info(f"Switched active profile to '{profile_name}' — wrote {marker_path}")
        return profile_name

    def get_active_marker_path(self) -> Path:
        """返回 active_profile 标记文件路径（供外部读取）"""
        return self._harness_dir / self._ACTIVE_PROFILE_FILENAME

    def _read_marker(self) -> Optional[str]:
        """读取 active_profile 标记文件内容"""
        marker_path = self._harness_dir / self._ACTIVE_PROFILE_FILENAME
        if marker_path.exists():
            try:
                content = marker_path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception as e:
                logger.warning(f"Failed to read active_profile marker: {e}")
        return None

    def _read_env_var(self, var_name: str) -> Optional[str]:
        """从 .harness/env 文件读取指定环境变量值

        .harness/env 格式: KEY=VALUE 每行一个，# 开头为注释，如:
          # harness-cook 运行时配置（activate 写入，gitignored）
          HARNESS_COOK_ROOT=/path/to/harness-cook
          HARNESS_PROFILE=frontend  # 仅初始化时生效，日常编辑 .harness/profiles/*.yaml 即可
          HARNESS_PROFILE=frontend  # 仅初始化时生效，日常编辑 .harness/profiles/*.yaml 即可
        """
        env_file = self._harness_dir / "env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").strip().splitlines():
                    stripped = line.strip()
                    # 跳过注释行和空行
                    if not stripped or stripped.startswith("#"):
                        continue
                    if stripped.startswith(f"{var_name}="):
                        # 去掉行尾注释：KEY=VALUE # comment → VALUE
                        value_part = stripped.split("=", 1)[1]
                        if "#" in value_part:
                            value_part = value_part.split("#", 1)[0]
                        value = value_part.strip()
                        if value:
                            return value
            except Exception as e:
                logger.warning(f"Failed to read .harness/env: {e}")
        return None

    # ─── Profile 加载/保存 ────────────────────────────────────

    def load(self, profile_name: Optional[str] = None) -> ProfileConfig:
        """
        加载 Profile。

        分层查找——项目级同名 profile 可覆盖内置 preset：
          1. 项目级 .harness/profiles/<name>.yaml → 优先（项目自定义）
          2. 内置 packages/core/harness/profiles/<name>.yaml → 兜底（框架预设）
          3. 都没有 → 返回默认 ProfileConfig(name=profile_name)

        加载后自动校验 hooks 中 skill_id 的存在性（E-10）。

        Args:
            profile_name: Profile 名称（对应文件名，不含 .yaml 后缀）。
                          None 时自动调用 resolve_active() 决定。

        Returns:
            ProfileConfig，如果文件不存在返回默认配置
        """
        if profile_name is None:
            profile_name = self.resolve_active()

        # 1️⃣ 项目级 profile（优先）
        profile_path = self._profiles_dir / f"{profile_name}.yaml"
        if profile_path.exists():
            data = self._read_file(profile_path)
            if data:
                profile = self._dict_to_profile(data, profile_name)
                profile.layer = "project"
                logger.info(f"Loaded project-level profile '{profile_name}' from {profile_path}")
                self._validate_hooks_skill_ids(profile)
                return profile

        # 2️⃣ 内置 preset profile（兜底）
        if self._builtin_profiles_dir:
            builtin_path = self._builtin_profiles_dir / f"{profile_name}.yaml"
            if builtin_path.exists():
                data = self._read_file(builtin_path)
                if data:
                    profile = self._dict_to_profile(data, profile_name)
                    profile.layer = "project"  # 内置也视为项目级基线
                    logger.info(f"Loaded builtin profile '{profile_name}' from {builtin_path}")
                    self._validate_hooks_skill_ids(profile)
                    return profile

        # 3️⃣ 都没有 → 返回默认
        logger.info(f"Profile '{profile_name}' not found in project or builtin — using defaults")
        return ProfileConfig(name=profile_name)

    # ─── S-3: 个性化治理分层加载 ────────────────────────────

    def load_with_layers(
        self,
        profile_name: Optional[str] = None,
    ) -> ProfileConfig:
        """S-3：三级分层加载 + 合并

        加载顺序：
          1. 项目级 Profile（.harness/profiles/）→ 最高优先级，强制项不可被覆盖
          2. 团队级 Profile（~/.harness/team-profiles/）→ 中间优先级
          3. 用户级 Profile（~/.harness/profiles/）→ 最低优先级

        合并策略由 merge_profiles() 实现——项目级 forced_keys 不被覆盖。

        Args:
            profile_name: Profile 名称。None 时自动 resolve。

        Returns:
            合并后的 ProfileConfig（layer="merged"）
        """
        from harness.types import merge_profiles

        if profile_name is None:
            profile_name = self.resolve_active()

        # 加载项目级 Profile
        project_profile = self.load(profile_name)

        # 加载团队级 Profile
        team_profile = self._load_team_profile(profile_name)

        # 加载用户级 Profile
        user_profile = self._load_user_profile(profile_name)

        # 如果只有项目级，直接返回（无需合并）
        if team_profile is None and user_profile is None:
            return project_profile

        # S-3 合并
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
            user_profile=user_profile,
        )

        logger.info(
            f"S-3: Merged profile '{profile_name}' "
            f"(project + {team_profile is not None and 'team' or ''} "
            f"+ {user_profile is not None and 'user' or ''})"
        )

        return merged

    def _load_team_profile(self, profile_name: str) -> Optional[ProfileConfig]:
        """加载团队级 Profile

        团队级 Profile 位置：~/.harness/team-profiles/<name>.yaml

        Args:
            profile_name: Profile 名称

        Returns:
            团队级 ProfileConfig，不存在返回 None
        """
        team_dir = Path.home() / ".harness" / "team-profiles"
        team_path = team_dir / f"{profile_name}.yaml"

        if not team_path.exists():
            return None

        data = self._read_file(team_path)
        if data:
            profile = self._dict_to_profile(data, profile_name)
            profile.layer = "team"
            logger.info(f"Loaded team-level profile '{profile_name}' from {team_path}")
            return profile

        return None

    def _load_user_profile(self, profile_name: str) -> Optional[ProfileConfig]:
        """加载用户级 Profile

        用户级 Profile 位置：~/.harness/profiles/<name>.yaml

        Args:
            profile_name: Profile 名称

        Returns:
            用户级 ProfileConfig，不存在返回 None
        """
        user_dir = Path.home() / ".harness" / "profiles"
        user_path = user_dir / f"{profile_name}.yaml"

        if not user_path.exists():
            return None

        data = self._read_file(user_path)
        if data:
            profile = self._dict_to_profile(data, profile_name)
            profile.layer = "user"
            logger.info(f"Loaded user-level profile '{profile_name}' from {user_path}")
            return profile

        return None

    def _validate_hooks_skill_ids(self, profile: ProfileConfig) -> List[str]:
        """E-10：校验 Profile hooks 中引用的 skill_id 是否在 SkillRegistry 中已注册。

        校验策略：
          - 对每个 hook 配置中 type="skill" 的条目检查 skill_id
          - skill_id 不存在 → warning 日志 + 记录到配置校验错误列表
          - 不阻断加载流程——仅发出警告（skill 可能稍后注册）

        Args:
            profile: 已加载的 ProfileConfig

        Returns:
            不存在的 skill_id 列表（空列表表示全部合法）
        """
        from harness.skill_registry import SkillRegistry, get_skill_registry

        missing_ids: List[str] = []
        hooks = profile.hooks

        if not hooks:
            return missing_ids

        try:
            registry = get_skill_registry()
        except Exception:
            # SkillRegistry 不可用——跳过校验
            logger.debug("SkillRegistry not available — skipping skill_id validation")
            return missing_ids

        for slot_name, hook_list in hooks.items():
            for hook_config in hook_list:
                if isinstance(hook_config, dict) and hook_config.get("type") == "skill":
                    skill_id = hook_config.get("skill_id", "")
                    if skill_id and not registry.has(skill_id):
                        missing_ids.append(skill_id)
                        logger.warning(
                            f"E-10: Hook skill_id '{skill_id}' not found in SkillRegistry "
                            f"(slot={slot_name}, profile={profile.name}). "
                            f"This skill may not be registered yet or the reference is invalid."
                        )

        if missing_ids:
            logger.warning(
                f"E-10: Profile '{profile.name}' has {len(missing_ids)} unregistered skill_id(s): "
                f"{missing_ids}. Configuration validation failed for these references."
            )
        else:
            logger.debug(f"E-10: All skill_id references in profile '{profile.name}' are valid")

        return missing_ids

    def list_profiles(self) -> list[str]:
        """列出所有可用的 Profile——合并项目级和内置两层"""
        profiles = set()

        # 项目级
        if self._profiles_dir.exists():
            profiles.update(p.stem for p in self._profiles_dir.glob("*.yaml"))

        # 内置 preset
        if self._builtin_profiles_dir and self._builtin_profiles_dir.exists():
            profiles.update(p.stem for p in self._builtin_profiles_dir.glob("*.yaml"))

        return sorted(profiles) if profiles else ["default"]

    def save(self, profile: ProfileConfig) -> None:
        """保存 Profile 到文件"""
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_path = self._profiles_dir / f"{profile.name}.yaml"
        data = self._profile_to_dict(profile)
        content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
        profile_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved profile '{profile.name}' to {profile_path}")

    # ─── 内部方法 ────────────────────────────────────

    def _read_file(self, path: Path) -> Optional[dict]:
        """读取 YAML 文件"""
        try:
            content = path.read_text(encoding="utf-8")
            return yaml.safe_load(content) or {}
        except Exception as e:
            logger.error(f"Failed to read profile {path}: {e}")
            return None

    def _dict_to_profile(self, data: dict, name: str = "default") -> ProfileConfig:
        """将字典转为 ProfileConfig"""
        from harness.types import GateMode, StepConfig, WorkflowConfig
        from harness.integrations.engine_config import (
            GuardrailsEngineConfig, ComplianceEngineConfig, AuditEngineConfig,
        )

        profile_data = data.get("profile", data)

        # 工作流步骤
        workflow = None
        pipeline_data = data.get("pipeline", {})
        steps_data = pipeline_data.get("steps", [])
        if steps_data:
            steps = []
            for s in steps_data:
                steps.append(StepConfig(
                    name=s.get("name", ""),
                    skill=s.get("skill", ""),
                    condition=s.get("condition", ""),
                    parallel=s.get("parallel", False),
                    hooks_pre=s.get("hooks_pre", []),
                    hooks_post=s.get("hooks_post", []),
                ))
            workflow = WorkflowConfig(
                name=pipeline_data.get("name", name),
                description=pipeline_data.get("description", ""),
                vars=pipeline_data.get("vars", {}),
                steps=steps,
            )

        # Gate 模式
        gates_data = data.get("gates", {})
        gate_mode_str = gates_data.get("default_mode", "hybrid")
        gate_mode_map = {"strict": GateMode.STRICT, "hybrid": GateMode.HYBRID, "loose": GateMode.LOOSE}
        gate_mode = gate_mode_map.get(gate_mode_str, GateMode.HYBRID)

        # Agent
        agent_data = data.get("agent", {})

        # ─── 治理集成总线引擎配置 ───
        guardrails_data = data.get("guardrails_engine", None)
        guardrails_engine = None
        if guardrails_data:
            guardrails_engine = GuardrailsEngineConfig(
                engine=guardrails_data.get("engine", "builtin"),
                config=guardrails_data.get("config", {}),
            )

        compliance_data = data.get("compliance_engine", None)
        compliance_engine = None
        if compliance_data:
            compliance_engine = ComplianceEngineConfig(
                engines=compliance_data.get("engines", ["builtin"]),
                language_routing=compliance_data.get("language_routing", {}),
                config=compliance_data.get("config", {}),
            )

        audit_data = data.get("audit_engine", None)
        audit_engine = None
        if audit_data:
            audit_engine = AuditEngineConfig(
                backends=audit_data.get("backends", ["local"]),
                trace_format=audit_data.get("trace_format", "builtin"),
                collector_url=audit_data.get("collector_url", ""),
                config=audit_data.get("config", {}),
            )

        return ProfileConfig(
            name=profile_data.get("name", name),
            description=profile_data.get("description", ""),
            default_agent=agent_data.get("adapter", "claude-code"),
            pipeline_agents=pipeline_data.get("agents", ["analyst", "coder", "validator", "committer"]),
            workflow=workflow,
            skill_slots=data.get("skill_slots", {}),
            hooks=data.get("hooks", {}),
            default_gate_mode=gate_mode,
            gate_checks=gates_data.get("checks", []),
            constraints=data.get("constraints", {}),
            default_spec=_parse_spec_defaults(data.get("spec_defaults")),
            guardrails_engine=guardrails_engine,
            compliance_engine=compliance_engine,
            audit_engine=audit_engine,
        )

    def _profile_to_dict(self, profile: ProfileConfig) -> dict:
        """将 ProfileConfig 转为字典（用于保存）"""
        result: dict = {
            "profile": {
                "name": profile.name,
                "description": profile.description,
            },
            "agent": {
                "adapter": profile.default_agent,
            },
            "pipeline": {
                "agents": profile.pipeline_agents,
            },
            "hooks": profile.hooks,
            "gates": {
                "default_mode": profile.default_gate_mode.value,
                "checks": profile.gate_checks,
            },
        }

        if profile.skill_slots:
            result["skill_slots"] = profile.skill_slots

        if profile.workflow:
            result["pipeline"]["steps"] = [
                {
                    "name": s.name,
                    "skill": s.skill,
                    "condition": s.condition,
                    "parallel": s.parallel,
                    "hooks_pre": s.hooks_pre,
                    "hooks_post": s.hooks_post,
                }
                for s in profile.workflow.steps
            ]

        if profile.constraints:
            result["constraints"] = profile.constraints

        # spec_defaults 序列化
        if profile.default_spec:
            result["spec_defaults"] = {
                "objective_template": profile.default_spec.objective,
                "acceptance_criteria": profile.default_spec.acceptance_criteria,
            }

        # ─── 治理集成总线引擎配置序列化 ───
        if profile.guardrails_engine:
            result["guardrails_engine"] = {
                "engine": profile.guardrails_engine.engine,
                "config": profile.guardrails_engine.config,
            }

        if profile.compliance_engine:
            result["compliance_engine"] = {
                "engines": profile.compliance_engine.engines,
                "language_routing": profile.compliance_engine.language_routing,
                "config": profile.compliance_engine.config,
            }

        if profile.audit_engine:
            result["audit_engine"] = {
                "backends": profile.audit_engine.backends,
                "trace_format": profile.audit_engine.trace_format,
                "collector_url": profile.audit_engine.collector_url,
                "config": profile.audit_engine.config,
            }

        return result


def load_profile(profile_name: Optional[str] = None, profiles_dir: Optional[str] = None) -> ProfileConfig:
    """加载 Profile——便捷函数。profile_name=None 时自动 resolve_active()"""
    loader = ProfileLoader(profiles_dir)
    if profile_name is None:
        profile_name = loader.resolve_active()
    return loader.load(profile_name)


def resolve_active_profile(profiles_dir: Optional[str] = None) -> str:
    """自动决定活跃 Profile——便捷函数"""
    return ProfileLoader(profiles_dir).resolve_active()


def switch_profile(profile_name: str, profiles_dir: Optional[str] = None) -> str:
    """切换活跃 Profile——便捷函数"""
    return ProfileLoader(profiles_dir).switch(profile_name)


def list_profiles(profiles_dir: Optional[str] = None) -> list[str]:
    """列出 Profile——便捷函数"""
    return ProfileLoader(profiles_dir).list_profiles()


# ─── spec_defaults 解析辅助 ────────────────────────────────────

def _parse_spec_defaults(spec_data: Optional[dict]) -> Optional["TaskSpec"]:
    """
    解析 YAML 中的 spec_defaults 段为 TaskSpec 对象。

    YAML 格式:
        spec_defaults:
          objective_template: "按前端最佳实践完成任务"
          acceptance_criteria:
            - "组件关注点分离"
            - "无 XSS 风险"

    Args:
        spec_data: spec_defaults 字典，或 None

    Returns:
        TaskSpec 对象，或 None（spec_data 为空时）
    """
    if not spec_data:
        return None

    from harness.types import TaskSpec

    objective = spec_data.get("objective_template", "")
    criteria = spec_data.get("acceptance_criteria", [])

    return TaskSpec(
        objective=objective,
        acceptance_criteria=criteria if criteria else [],
    )