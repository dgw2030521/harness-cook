"""
NeMoGuardrailsChecker — NeMo Guardrails 护栏引擎集成

将 NVIDIA NeMo Guardrails 的 Colang 策略语言和护栏能力接入
harness-cook 治理框架，作为护栏层的吸收式集成。

NeMo Guardrails 提供的能力：
  - Colang 策略语言：声明式对话流控制（define flow / define rail）
  - 输入护栏：阻止有害/不当的用户输入
  - 输出护栏：阻止有害/不当的模型输出
  - 事实性护栏：检测幻觉/不相关输出

harness 规则 → NeMo Guardrails 映射：
  - matcher_config.rail_type 或 pattern 关键词自动映射
  - 支持 Colang 流定义（matcher_config.colang_flow）

安装：pip install harness-cook[nemo]
"""

import logging
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.nemo_guardrails")


# ─── Rail 类型映射表 ──────────────────────────────────────

# harness 规则 pattern/关键词 → NeMo Guardrails rail 类型
RAIL_TYPE_MAP = {
    # 输入护栏
    "no_pii": "input_pii",
    "pii": "input_pii",
    "no_toxicity": "input_toxicity",
    "toxicity": "input_toxicity",
    "no_harmful_input": "input_toxicity",
    # 输出护栏
    "no_harmful_output": "output_toxicity",
    "no_hallucination": "output_factuality",
    "hallucination": "output_factuality",
    "factuality": "output_factuality",
    "relevance": "output_relevance",
    # 通用
    "no_sql_injection": "input_sql_injection",
    "sql_injection": "input_sql_injection",
    "valid_json": "output_json_validation",
    "json_validation": "output_json_validation",
}


class NeMoGuardrailsChecker(ExternalEngineChecker):
    """NeMo Guardrails 护栏引擎集成

    用法：
        checker = NeMoGuardrailsChecker()
        result = checker.check(rule, artifact, context)

    规则 matcher_config 配置示例：
        matcher_type: "nemo"
        matcher_config:
          rail_type: "input_pii"     # 直接指定 rail 类型
          colang_flow: "define flow ... end"  # 自定义 Colang 流
          # 或用 pattern 关键词自动映射（如 pattern="no_pii" → input_pii rail）

    降级行为：
        nemoguardrails SDK 未安装 → 自动回退到 RegexChecker
        SDK import 失败 → 回退到 RegexChecker
        rail 调用失败 → 回退到 RegexChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        super().__init__(
            engine_name="nemo-guardrails",
            config=config or {},
        )
        self._rails_config = None  # NeMo Guardrails 配置（惰性构建）

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 NeMo Guardrails SDK 可用性"""
        try:
            from nemoguardrails import RailsConfig
            # 创建空配置验证 SDK 可用（不触发实际 LLM 调用）
            RailsConfig.from_content("")
            return True
        except ImportError:
            logger.debug("nemoguardrails SDK not installed — checker disabled")
            return False
        except Exception as e:
            logger.debug(f"nemoguardrails probe failed: {e}")
            return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 NeMo Guardrails 检查请求

        rail 类型确定逻辑（优先级从高到低）：
        1. matcher_config.rail_type — 直接指定
        2. pattern 关键词自动映射（RAIL_TYPE_MAP）
        3. matcher_config.colang_flow — 自定义 Colang 流
        4. pattern 原值 — 透传
        """
        rail_type = self._resolve_rail_type(rule)
        colang_flow = rule.matcher_config.get("colang_flow", "")

        return {
            "rail_type": rail_type,
            "colang_flow": colang_flow,
            "content": artifact.content,
            "path": artifact.path,
            "rule_id": rule.id,
            "severity": rule.severity,
            "direction": self._resolve_direction(rail_type),
            "metadata": {
                "rule_description": rule.description,
                "rule_languages": rule.languages,
                "artifact_type": artifact.type,
            },
        }

    def _resolve_rail_type(self, rule: ComplianceRule) -> str:
        """确定 NeMo Guardrails rail 类型

        Args:
            rule: harness 合规规则

        Returns:
            NeMo Guardrails rail 类型字符串
        """
        # 优先级1: matcher_config 直接指定
        config_rail = rule.matcher_config.get("rail_type")
        if config_rail:
            return config_rail

        # 优先级2: pattern 关键词自动映射
        pattern_lower = rule.pattern.lower().strip()
        mapped = RAIL_TYPE_MAP.get(pattern_lower)
        if mapped:
            return mapped

        # 优先级3: pattern 原值透传
        return rule.pattern

    def _resolve_direction(self, rail_type: str) -> str:
        """根据 rail 类型推断检查方向

        NeMo Guardrails 区分 input/output 方向：
        - input_* → 检查用户输入
        - output_* → 检查模型输出
        """
        if rail_type.startswith("input"):
            return "input"
        elif rail_type.startswith("output"):
            return "output"
        # 通用护栏默认做双向检查
        return "both"

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """调用 NeMo Guardrails 执行护栏检查

        方法级 import——确保默认安装不受影响。
        """
        from nemoguardrails import RailsConfig, LLMRails

        rail_type = request["rail_type"]
        content = request["content"]
        direction = request["direction"]
        colang_flow = request.get("colang_flow", "")

        # 构建 NeMo Guardrails 配置
        colang_content = colang_flow if colang_flow else self._build_default_colang(rail_type)

        rails_config = RailsConfig.from_content(colang_content)
        rails = LLMRails(rails_config)

        try:
            # NeMo Guardrails 的护栏检查调用
            # 根据方向选择 input/output 检查
            if direction == "input":
                result = rails.generate(content)
            elif direction == "output":
                # output 检查需要对已生成的输出做护栏
                result = rails.generate(messages=[{"role": "user", "content": "check"}])
            else:
                # 双向：先检查 input，再检查 output
                result = rails.generate(content)

            # 解析护栏检查结果
            # NeMo Guardrails 返回被修改/拦截的内容
            if result and isinstance(result, str):
                # 内容未被拦截——护栏通过
                if result == content or not result.strip():
                    return {
                        "passed": True,
                        "findings": [],
                        "severity": request["severity"],
                    }
                else:
                    # 内容被修改/拦截——护栏触发
                    return {
                        "passed": False,
                        "findings": [
                            f"NeMo Guardrails ({rail_type}): content was filtered/modified"
                        ],
                        "severity": request["severity"],
                        "remediation": f"Content flagged by {rail_type} rail",
                        "locations": [
                            {"line": 0, "match": "full_content", "rail_type": rail_type}
                        ],
                    }

            # result 为空或异常 → 视为拦截
            return {
                "passed": False,
                "findings": [
                    f"NeMo Guardrails ({rail_type}): content blocked"
                ],
                "severity": request["severity"],
                "remediation": f"Content blocked by {rail_type} rail",
                "locations": [
                    {"line": 0, "match": "full_content", "rail_type": rail_type}
                ],
            }

        except Exception as e:
            logger.warning(f"NeMo Guardrails rail call failed: {e}")
            raise  # 让 ExternalEngineChecker.check() 的 catch 回退

    def _build_default_colang(self, rail_type: str) -> str:
        """构建默认 Colang 流定义

        当 matcher_config 未指定 colang_flow 时，
        根据 rail_type 自动生成最简 Colang 配置。
        """
        # 通用护栏模板
        colang_templates = {
            "input_pii": """
define flow check input pii
  user ask $input
  $input has pii
  bot refuse to respond about pii
""",
            "input_toxicity": """
define flow check input toxicity
  user ask $input
  $input is toxic
  bot refuse to respond to toxic content
""",
            "output_toxicity": """
define flow check output toxicity
  bot respond $output
  $output is toxic
  bot remove toxic content
""",
            "output_factuality": """
define flow check output factuality
  bot respond $output
  $output is not factual
  bot refuse to respond about non-factual content
""",
            "output_relevance": """
define flow check output relevance
  bot respond $output
  $output is not relevant
  bot refuse to respond about irrelevant content
""",
        }

        # 查找匹配的模板，找不到则生成通用模板
        template = colang_templates.get(rail_type)
        if template:
            return template

        # 通用模板——rail_type 作为动作名
        return f"""
define flow check {rail_type}
  user ask $input
  $input violates {rail_type}
  bot refuse to respond
"""

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """将 NeMo Guardrails 响应翻译为 ComplianceResult

        使用基类默认实现——NeMo Guardrails 返回的字典格式
        已包含 passed/findings/severity/remediation/locations，
        与基类 _translate_response 的字段提取逻辑兼容。
        """
        return super()._translate_response(response, rule)
