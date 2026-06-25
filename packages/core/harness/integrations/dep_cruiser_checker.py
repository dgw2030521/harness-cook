"""
DepCruiserChecker — JS/TS 依赖合规引擎集成

dependency-cruiser 是 JS/TS 生态的依赖分析工具，
通过 .dependency-cruiser.js 配置声明依赖规则。
harness-cook 以子进程方式调用 depcruise --validate，实现 JS/TS 依赖合规检查。

工作流程：
1. _probe_engine: 检查 dependency-cruiser CLI
2. _translate_request: matcher_config → depcruise 参数
3. _call_engine: 子进程执行 depcruise --validate
4. _translate_response: 验证结果 → ComplianceResult

降级到内置 DependencyGraphChecker。

安装：pip install harness-cook[dep_cruiser]（或 npm install dependency-cruiser）
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

logger = logging.getLogger("harness.integrations.dep_cruiser")


class DepCruiserChecker(ExternalEngineChecker):
    """dep-cruiser JS/TS 依赖合规引擎

    用法：
        checker = DepCruiserChecker(config={
            "depcruise_cmd": "depcruise",
            "cruise_config": ".dependency-cruiser.js",
        })

    规则 matcher_config 配置示例：
        matcher_type: "dep_cruiser"
        matcher_config:
          check: "dependency_violation"
          cruise_config: ".dependency-cruiser.js"
          # 或使用默认项目配置

    降级行为：
        dependency-cruiser CLI 不安装 → 回退到 DependencyGraphChecker
        配置文件不存在 → 回退到 DependencyGraphChecker
        执行失败 → 回退到 DependencyGraphChecker
    """

    def __init__(
        self,
        config: Optional[dict] = None,
    ):
        from harness.rule_checker import DependencyGraphChecker
        super().__init__(
            engine_name="dep_cruiser",
            fallback_checker=DependencyGraphChecker(),
            config=config or {},
        )

    # ─── 可用性探测 ──────────────────────────────────

    def _probe_engine(self) -> bool:
        """探测 dependency-cruiser CLI"""
        cmd = self._config.get("depcruise_cmd", "depcruise")

        # 也检查 npx 方式
        cmds_to_try = [cmd, "npx", "depcruise"]
        if cmd not in cmds_to_try:
            cmds_to_try.insert(0, cmd)

        for try_cmd in cmds_to_try:
            try:
                args = [try_cmd, "--version"]
                if try_cmd == "npx":
                    args = ["npx", "dependency-cruiser", "--version"]

                result = subprocess.run(
                    args, capture_output=True, timeout=5, text=True,
                )
                if result.returncode == 0:
                    self._config["depcruise_cmd"] = try_cmd
                    if try_cmd == "npx":
                        self._config["depcruise_cmd"] = "npx"
                        self._config["use_npx"] = True
                    logger.debug(f"dependency-cruiser available via {try_cmd}")
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        logger.debug("dependency-cruiser CLI not found")
        return False

    # ─── 请求翻译 ────────────────────────────────────

    def _translate_request(
        self,
        rule: ComplianceRule,
        artifact: Artifact,
        context: ScanContext,
    ) -> dict:
        """将 harness 规则翻译为 depcruise 参数"""
        cruise_config = rule.matcher_config.get(
            "cruise_config",
            self._config.get("cruise_config", ""),
        )

        # 自动查找配置文件
        if not cruise_config and context.project_root:
            common_configs = [
                ".dependency-cruiser.js",
                ".dependency-cruiser.json",
                ".dependency-cruiser.cjs",
            ]
            for cfg in common_configs:
                cfg_path = os.path.join(context.project_root, cfg)
                if os.path.isfile(cfg_path):
                    cruise_config = cfg
                    break

        return {
            "cruise_config": cruise_config,
            "project_root": context.project_root or self._config.get("project_root", ""),
            "artifact_path": artifact.path,
            "rule_id": rule.id,
            "severity": rule.severity,
            "depcruise_cmd": self._config.get("depcruise_cmd", "depcruise"),
            "use_npx": self._config.get("use_npx", False),
        }

    # ─── 引擎调用 ────────────────────────────────────

    def _call_engine(self, request: dict) -> dict:
        """子进程执行 depcruise --validate"""
        cmd = request["depcruise_cmd"]
        project_root = request["project_root"]
        cruise_config = request["cruise_config"]

        # 构建命令
        args = []
        if request.get("use_npx"):
            args = ["npx", "dependency-cruiser", project_root, "--validate"]
        else:
            args = [cmd, project_root, "--validate"]

        if cruise_config:
            args.extend(["-c", cruise_config])

        # 输出格式 JSON
        args.extend(["--output-type", "json"])

        try:
            result = subprocess.run(
                args, capture_output=True, timeout=30, text=True,
            )

            # depcruise 输出 JSON 格式的验证结果
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # 非 JSON 输出 → 解析文本
                return self._parse_text_output(result.stdout, result.returncode, request)

            return self._parse_json_output(data, request)

        except subprocess.TimeoutExpired:
            logger.warning("dependency-cruiser timed out")
            raise
        except Exception as e:
            logger.warning(f"dependency-cruiser failed: {e}")
            raise

    def _parse_json_output(self, data: dict, request: dict) -> dict:
        """解析 depcruise JSON 输出"""
        # depcruise JSON 输出包含 modules 和 violations
        violations = data.get("violations", [])

        if not violations:
            return {
                "passed": True,
                "findings": [],
                "severity": request["severity"],
            }

        findings = []
        locations = []
        for v in violations:
            rule_name = v.get("rule", {}).get("name", "unknown")
            from_module = v.get("from", "unknown")
            to_module = v.get("to", "unknown")
            message = v.get("message", f"dependency violation: {from_module} → {to_module}")

            findings.append(f"dep-cruiser ({rule_name}): {message}")
            locations.append({
                "line": 0,
                "match": f"{from_module} → {to_module}",
                "start": 0,
                "end": 0,
                "from": from_module,
                "to": to_module,
                "engine": "dep_cruiser",
            })

        return {
            "passed": False,
            "findings": findings[:10],
            "severity": request["severity"],
            "remediation": f"Fix {len(violations)} dependency violations",
            "locations": locations[:10],
        }

    def _parse_text_output(self, output: str, returncode: int, request: dict) -> dict:
        """解析 depcruise 文本输出（fallback）"""
        if returncode == 0:
            return {
                "passed": True,
                "findings": [],
                "severity": request["severity"],
            }

        findings = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if line and "error" in line.lower() or "violation" in line.lower():
                findings.append(f"dep-cruiser: {line}")

        if not findings:
            findings.append("dep-cruiser: dependency validation failed")

        return {
            "passed": False,
            "findings": findings[:10],
            "severity": request["severity"],
            "remediation": "Fix dependency violations",
            "locations": [],
        }

    # ─── 响应翻译 ────────────────────────────────────

    def _translate_response(
        self,
        response: dict,
        rule: ComplianceRule,
    ) -> ComplianceResult:
        """使用基类默认实现"""
        return super()._translate_response(response, rule)
