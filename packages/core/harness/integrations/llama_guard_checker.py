"""
LlamaGuardChecker — Meta Llama Guard 护栏引擎集成

将 Meta Llama Guard 的安全分类能力接入 harness-cook 治理框架，
作为护栏层的吸收式集成。

Llama Guard 提供的能力：
  - 输入安全分类：检测用户输入中的有害内容（暴力、自残、色情等）
  - 输出安全分类：检测模型输出中的有害内容
  - 多类别细粒度分类：6 大类 × 14 小类的 taxonomy

harness 规则 → Llama Guard 映射：
  - matcher_config.category 或 pattern 关键词自动映射
  - 支持 direction 参数（input/output）

安装：pip install harness-cook[llama-guard]
"""

import logging
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.llama_guard")


# ─── Category 映射表 ──────────────────────────────────────

# harness 规则 pattern/关键词 → Llama Guard category
# Llama Guard taxonomy: S1-S14 (6 大类细分)
CATEGORY_MAP = {
    # PII 相关 → S1 (Violent Crimes) 不直接匹配，用 PII 类别
    "no_pii": "pii_leak",
    "pii": "pii_leak",
    # 毒性相关
    "no_toxicity": "S1",
    "toxicity": "S1",
    "no_harmful_input": "S1",
    "no_harmful_output": "S1",
    # 幻觉/事实性
    "no_hallucination": "factuality",
    "hallucination": "factuality",
    "relevance": "relevance",
    # SQL 注入 → 特殊类别
    "no_sql_injection": "sql_injection",
    "sql_injection": "sql_injection",
    # 格式验证
    "valid_json": "json_validation",
    "json_validation": "json_validation",
    "valid_python": "code_validation",
    "python_validation": "code_validation",
}

# 方向映射：harness pattern → Llama Guard direction
DIRECTION_MAP = {
    "no_pii": "input",
    "pii": "input",
    "no_toxicity": "both",
    "toxicity": "both",
    "no_harmful_input": "input",
    "no_harmful_output": "output",
    "no_hallucination": "output",
    "hallucination": "output",
    "relevance": "output",
    "no_sql_injection": "input",
    "sql_injection": "input",
    "valid_json": "output",
    "valid_python": "output",
}


class LlamaGuardChecker(ExternalEngineChecker):
    """Meta Llama Guard 护栏引擎集成

    用法：
        checker = LlamaGuardChecker()
        result = checker.check(rule, artifact, context)

    规则 matcher_config 配置示例：
        matcher_type: "llama-guard"
        matcher_config:
          category: "S1"             # 直接指定 Llama Guard taxonomy 类别
          direction: "output"        # 检查方向：input/output/both
          model_name: "llama-guard-3"  # 模型名（默认 Llama-Guard-3）

    降级行为：
        llama-guard SDK 或 transformers 未安装 → 自动回退到 RegexChecker
        模型加载失败 → 回退到 RegexChecker
        分类调用失败 → 回退到 RegexChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        super().__init__(
            engine_name="llama-guard",
            config=config or {},
        )
        self._model = None  # 惰性加载的 Llama Guard 模型

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 Llama Guard SDK 可用性

        Llama Guard 基于 HuggingFace transformers，
        需要 transformers + torch/tensorflow 可用。
        """
        try:
            import transformers
            # 验证 AutoModelForCausalLM 可导入（不实际加载模型）
            from transformers import AutoModelForCausalLM, AutoTokenizer
            return True
        except ImportError:
            logger.debug(
                "transformers/torch not installed — LlamaGuardChecker disabled"
            )
            return False
        except Exception as e:
            logger.debug(f"Llama Guard probe failed: {e}")
            return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 Llama Guard 分类请求

        category 确定逻辑（优先级从高到低）：
        1. matcher_config.category — 直接指定
        2. pattern 关键词自动映射（CATEGORY_MAP）
        3. pattern 原值 — 透传
        """
        category = self._resolve_category(rule)
        direction = self._resolve_direction(rule)
        model_name = rule.matcher_config.get("model_name", "meta-llama/Llama-Guard-3-8B")

        return {
            "category": category,
            "direction": direction,
            "model_name": model_name,
            "content": artifact.content,
            "path": artifact.path,
            "rule_id": rule.id,
            "severity": rule.severity,
            "metadata": {
                "rule_description": rule.description,
                "artifact_type": artifact.type,
            },
        }

    def _resolve_category(self, rule: ComplianceRule) -> str:
        """确定 Llama Guard 分类类别

        Args:
            rule: harness 合规规则

        Returns:
            Llama Guard taxonomy 类别字符串
        """
        # 优先级1: matcher_config 直接指定
        config_category = rule.matcher_config.get("category")
        if config_category:
            return config_category

        # 优先级2: pattern 关键词自动映射
        pattern_lower = rule.pattern.lower().strip()
        mapped = CATEGORY_MAP.get(pattern_lower)
        if mapped:
            return mapped

        # 优先级3: pattern 原值透传
        return rule.pattern

    def _resolve_direction(self, rule: ComplianceRule) -> str:
        """确定检查方向

        Args:
            rule: harness 合规规则

        Returns:
            "input" | "output" | "both"
        """
        # matcher_config 优先
        config_dir = rule.matcher_config.get("direction")
        if config_dir:
            return config_dir

        # pattern 关键词映射
        pattern_lower = rule.pattern.lower().strip()
        mapped = DIRECTION_MAP.get(pattern_lower)
        if mapped:
            return mapped

        # 默认双向检查
        return "both"

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """调用 Llama Guard 执行安全分类

        Llama Guard 基于 transformers 模型推理。
        方法级 import——确保默认安装不受影响。
        """
        from transformers import AutoModelForCausalLM, AutoTokenizer

        content = request["content"]
        direction = request["direction"]
        model_name = request["model_name"]

        # 惰性加载模型（首次调用加载，后续缓存）
        if self._model is None:
            try:
                tokenizer = AutoTokenizer.from_pretrained(model_name)
                model = AutoModelForCausalLM.from_pretrained(model_name)
                self._model = {"tokenizer": tokenizer, "model": model}
            except Exception as e:
                logger.warning(f"Llama Guard model loading failed: {e}")
                raise

        tokenizer = self._model["tokenizer"]
        model = self._model["model"]

        # 构建分类 prompt
        # Llama Guard 的标准 prompt 格式
        if direction == "input":
            prompt = f"[INST] Task: Check if the user input is safe.\nUser: {content} [/INST]"
        elif direction == "output":
            prompt = f"[INST] Task: Check if the AI output is safe.\nAI: {content} [/INST]"
        else:
            # 双向检查——同时检查输入和输出
            prompt = f"[INST] Task: Check if the content is safe.\nContent: {content} [/INST]"

        try:
            # 模型推理
            inputs = tokenizer(prompt, return_tensors="pt")
            outputs = model.generate(**inputs, max_new_tokens=128)
            result_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Llama Guard 输出格式：safe 或 unsafe + 类别
            # 解析分类结果
            is_safe = "safe" in result_text.lower()

            if is_safe:
                return {
                    "passed": True,
                    "findings": [],
                    "severity": request["severity"],
                }
            else:
                # 提取违规类别
                findings = []
                if "unsafe" in result_text.lower():
                    # Llama Guard 输出类别编号如 S1, S3 等
                    categories_found = self._extract_categories(result_text)
                    findings = [
                        f"Llama Guard: unsafe content detected ({', '.join(categories_found)})"
                    ] if categories_found else [
                        "Llama Guard: unsafe content detected"
                    ]

                return {
                    "passed": False,
                    "findings": findings,
                    "severity": request["severity"],
                    "remediation": "Content flagged by Llama Guard safety classifier",
                    "locations": [
                        {"line": 0, "match": "full_content", "categories": categories_found}
                    ],
                }

        except Exception as e:
            logger.warning(f"Llama Guard inference failed: {e}")
            raise  # 让 ExternalEngineChecker.check() 的 catch 回退

    def _extract_categories(self, result_text: str) -> list:
        """从 Llama Guard 输出中提取违规类别

        Llama Guard 输出格式示例：
          "unsafe\nS1" → ["S1"]
          "unsafe\nS1,S3" → ["S1", "S3"]
          "safe" → []
        """
        categories = []
        # 查找 S 开头的类别编号（S1-S14）
        import re
        matches = re.findall(r"S\d+", result_text)
        if matches:
            categories.extend(matches)

        # 也提取自定义类别（如 pii_leak, sql_injection）
        custom_matches = re.findall(
            r"(pii_leak|sql_injection|factuality|relevance|json_validation|code_validation)",
            result_text,
        )
        categories.extend(custom_matches)

        return categories

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """将 Llama Guard 响应翻译为 ComplianceResult

        使用基类默认实现——Llama Guard 返回的字典格式
        已包含 passed/findings/severity/remediation/locations，
        与基类 _translate_response 的字段提取逻辑兼容。
        """
        return super()._translate_response(response, rule)
