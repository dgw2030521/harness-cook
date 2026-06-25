"""
ArchUnitChecker — Java 架构合规引擎集成

ArchUnit 是 Java 生态的架构测试框架，通过 JUnit 测试声明架构规则。
harness-cook 以子进程方式调用 ArchUnit Java 测试，实现 Java 架构合规检查。

工作流程：
1. _probe_engine: 检查 JVM + ArchUnit jar
2. _translate_request: matcher_config → ArchUnit 测试参数
3. _call_engine: 子进程执行 ArchUnit Java 测试
4. _translate_response: 测试结果 → ComplianceResult

降级到内置 DependencyGraphChecker（跨文件依赖分析）。

安装：pip install harness-cook[archunit]（仅下载 ArchUnit jar）
前置：JDK 8+ 安装
"""

import json
import logging
import subprocess
import os
from typing import Optional

from harness.types import (
    Artifact, ComplianceRule, ComplianceResult, ScanContext,
)
from harness.integrations.base import ExternalEngineChecker

logger = logging.getLogger("harness.integrations.archunit")


class ArchUnitChecker(ExternalEngineChecker):
    """ArchUnit Java 架构合规引擎

    用法：
        checker = ArchUnitChecker(config={
            "java_home": "/usr/lib/jvm/java-11",
            "archunit_jar": "/opt/archunit/archunit.jar",
            "project_root": "/path/to/java/project",
        })

    规则 matcher_config 配置示例：
        matcher_type: "archunit"
        matcher_config:
          check: "layer_violation"       # 分层违规
          # 或 "no_cycles"（循环依赖）
          # 或 "naming_convention"（命名规范）
          layer_mapping:
            controller: "com.example.controller.."
            service: "com.example.service.."
            repository: "com.example.repository.."
          forbidden_directions:
            - from_layer: "controller"
              to_layer: "repository"

    降级行为：
        JVM 不安装 → 回退到 DependencyGraphChecker
        ArchUnit jar 不存在 → 回退到 DependencyGraphChecker
        Java 测试执行失败 → 回退到 DependencyGraphChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        from harness.rule_checker import DependencyGraphChecker
        super().__init__(
            engine_name="archunit",
            fallback_checker=DependencyGraphChecker(),
            config=config or {},
        )

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 JVM + ArchUnit jar"""
        java_home = self._config.get("java_home", "")
        java_cmd = "java"

        if java_home:
            java_cmd = os.path.join(java_home, "bin", "java")

        # 检查 JVM
        try:
            result = subprocess.run(
                [java_cmd, "-version"],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                logger.debug("JVM not available")
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("JVM not found")
            return False

        # 检查 ArchUnit jar
        jar_path = self._config.get("archunit_jar", "")
        if not jar_path:
            # 尝试在常见位置查找
            common_paths = [
                os.path.expanduser("~/.archunit/archunit.jar"),
                "/opt/archunit/archunit.jar",
                os.path.join(os.getcwd(), "archunit.jar"),
            ]
            for p in common_paths:
                if os.path.isfile(p):
                    jar_path = p
                    break

        if not jar_path or not os.path.isfile(jar_path):
            logger.debug("ArchUnit jar not found")
            return False

        # 缓存 jar_path
        self._config["archunit_jar"] = jar_path
        return True

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 ArchUnit 测试参数"""
        check_type = rule.matcher_config.get("check", "layer_violation")

        return {
            "check_type": check_type,
            "project_root": context.project_root or self._config.get("project_root", ""),
            "matcher_config": rule.matcher_config,
            "artifact_path": artifact.path,
            "rule_id": rule.id,
            "severity": rule.severity,
            "java_home": self._config.get("java_home", ""),
            "archunit_jar": self._config.get("archunit_jar", ""),
        }

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """子进程执行 ArchUnit Java 测试"""
        java_cmd = "java"
        if request.get("java_home"):
            java_cmd = os.path.join(request["java_home"], "bin", "java")

        jar_path = request.get("archunit_jar", "")
        if not jar_path:
            raise RuntimeError("ArchUnit jar path not resolved")

        # 构建测试参数 JSON
        test_params = json.dumps({
            "check_type": request["check_type"],
            "project_root": request["project_root"],
            "matcher_config": request["matcher_config"],
            "artifact_path": request["artifact_path"],
        })

        try:
            result = subprocess.run(
                [java_cmd, "-jar", jar_path, test_params],
                capture_output=True, timeout=30,
                text=True,
            )

            if result.returncode == 0:
                # ArchUnit 测试通过
                return {
                    "passed": True,
                    "findings": [],
                    "severity": request["severity"],
                }

            # 测试失败 → 解析输出
            output = result.stdout or result.stderr
            return self._parse_java_output(output, request)

        except subprocess.TimeoutExpired:
            logger.warning("ArchUnit Java test timed out")
            raise
        except Exception as e:
            logger.warning(f"ArchUnit Java test failed: {e}")
            raise

    def _parse_java_output(self, output: str, request: dict) -> dict:
        """解析 ArchUnit Java 测试输出"""
        # ArchUnit 输出通常是 JUnit 格式的断言错误信息
        findings = []
        locations = []

        # 简化的输出解析——提取 violation 信息
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("at ") and not line.startswith("Exception"):
                findings.append(f"ArchUnit: {line}")
                locations.append({
                    "line": 0,
                    "match": line[:50],
                    "start": 0,
                    "end": 0,
                    "engine": "archunit",
                })

        if not findings:
            findings.append(f"ArchUnit ({request['check_type']}): architecture violation detected")
            locations.append({"line": 0, "match": "architecture violation", "start": 0, "end": 0, "engine": "archunit"})

        return {
            "passed": False,
            "findings": findings[:10],  # 限制数量
            "severity": request["severity"],
            "remediation": f"Fix ArchUnit {request['check_type']} violations",
            "locations": locations[:10],
        }

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """使用基类默认实现"""
        return super()._translate_response(response, rule)
