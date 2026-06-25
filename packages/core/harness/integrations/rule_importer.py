"""
RuleImporter — 外部引擎规则导入器

将 SonarQube/ArchUnit/DepCruiser 的规则定义翻译为 harness-cook 的
ComplianceRule / RulePack 格式，可直接加载到 ComplianceEngine。

核心组件：
1. SonarQubeRuleImporter — 从 SonarQube API 导入规则
2. ArchUnitRuleImporter — 从 Java 测试解析规则
3. DepCruiserRuleImporter — 从 .dependency-cruiser.js 解析规则

所有导入器返回 RulePack，可直接加载到 ComplianceEngine。
"""

import json
import logging
import os
from typing import Optional, Dict, Any, List

from harness.types import ComplianceRule, ComplianceCategory

logger = logging.getLogger("harness.integrations.rule_importer")


# ─── SonarQube 严重性映射 ──────────────────────────────────────

SEVERITY_MAP = {
    "BLOCKER": "critical",
    "CRITICAL": "high",
    "MAJOR": "medium",
    "MINOR": "low",
    "INFO": "info",
}


class RulePack:
    """规则包——导入器的返回格式

    一个 RulePack 包含一组 ComplianceRule 和元数据，
    可直接加载到 ComplianceEngine。

    用法：
        pack = SonarQubeRuleImporter().import_rules(...)
        engine.load_pack(pack)
    """

    def __init__(
        self,
        name: str,
        rules: List[ComplianceRule],
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.rules = rules
        self.source = source
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"RulePack(name={self.name}, source={self.source}, rules={len(self.rules)})"


# ─── SonarQubeRuleImporter ────────────────────────────────────────


class SonarQubeRuleImporter:
    """SonarQube 规则导入器

    从 SonarQube /api/rules/search API 检索规则定义，
    翻译为 ComplianceRule 格式。

    用法：
        importer = SonarQubeRuleImporter(config={
            "sonarqube_url": "https://sonar.example.com",
            "sonarqube_token": "squ_xxxx...",
        })
        pack = importer.import_rules(
            project_key="my-project",
            languages=["python", "java"],
        )
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}

    def import_rules(
        self,
        project_key: Optional[str] = None,
        languages: Optional[List[str]] = None,
        rule_keys: Optional[List[str]] = None,
    ) -> RulePack:
        """从 SonarQube API 导入规则

        Args:
            project_key: SonarQube 项目键（可选，用于过滤项目相关规则）
            languages: 语言列表（如 ["python", "java"]）
            rule_keys: 指定规则键列表（可选）

        Returns:
            RulePack 包含翻译后的 ComplianceRule 列表
        """
        url = self._config.get("sonarqube_url", "")
        token = self._config.get("sonarqube_token", "")

        if not url:
            logger.warning("sonarqube_url not configured — returning empty pack")
            return RulePack(
                name="sonarqube_import",
                rules=[],
                source="sonarqube",
                metadata={"error": "url_not_configured"},
            )

        # 构建 API 查询
        api_url = f"{url.rstrip('/')}/api/rules/search"
        params = "ps=100"

        if languages:
            lang_str = ",".join(languages)
            params += f"&languages={lang_str}"

        if rule_keys:
            keys_str = ",".join(rule_keys)
            params += f"&rules={keys_str}"

        full_url = f"{api_url}?{params}"

        # 调用 API
        try:
            import urllib.request
            import urllib.error
            import base64

            req = urllib.request.Request(full_url)
            if token:
                credentials = base64.b64encode(f"{token}:".encode()).decode()
                req.add_header("Authorization", f"Basic {credentials}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            return self._translate_sonarqube_rules(data)

        except Exception as e:
            logger.warning(f"SonarQube rule import failed: {e}")
            return RulePack(
                name="sonarqube_import",
                rules=[],
                source="sonarqube",
                metadata={"error": str(e)},
            )

    def _translate_sonarqube_rules(self, data: dict) -> RulePack:
        """翻译 SonarQube 规则为 ComplianceRule"""
        sonar_rules = data.get("rules", [])
        rules = []

        for sr in sonar_rules:
            key = sr.get("key", "unknown")
            name = sr.get("name", key)
            severity = SEVERITY_MAP.get(sr.get("severity", ""), "medium")
            language = sr.get("lang", "unknown")
            description = sr.get("htmlDesc", sr.get("mdDesc", name))

            # 构建 ComplianceRule
            rule = ComplianceRule(
                id=f"sonarqube_{key}",
                category=ComplianceCategory.SECURITY,
                pattern=key,  # SonarQube 规则键作为 pattern
                severity=severity,
                description=f"{name}: {description[:200]}",  # 截断过长描述
                remediation=f"Fix SonarQube rule {key}",
                matcher_type="sonarqube",
                matcher_config={
                    "rule_key": key,
                    "language": language,
                },
            )
            rules.append(rule)

        return RulePack(
            name="sonarqube_import",
            rules=rules,
            source="sonarqube",
            metadata={
                "total": data.get("total", len(sonar_rules)),
                "imported": len(rules),
            },
        )


# ─── ArchUnitRuleImporter ─────────────────────────────────────────


class ArchUnitRuleImporter:
    """ArchUnit 规则导入器

    从 Java 测试文件或 JSON 配置解析 ArchUnit 架构规则，
    翻译为 ComplianceRule 格式。

    用法：
        importer = ArchUnitRuleImporter()
        pack = importer.import_rules(
            test_file="src/test/java/ArchitectureTest.java",
        )
        # 或从 JSON 配置导入
        pack = importer.import_rules_from_config(
            config_file="archunit-config.json",
        )
    """

    def import_rules(
        self,
        test_file: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> RulePack:
        """从 Java 测试文件导入 ArchUnit 规则

        解析 Java 测试文件中的 ArchUnit 规则声明，
        提取检查类型和包约束信息。

        Args:
            test_file: Java 测试文件路径
            project_root: 项目根目录

        Returns:
            RulePack 包含翻译后的 ComplianceRule 列表
        """
        rules = []

        if not test_file:
            logger.warning("No test file specified — returning empty pack")
            return RulePack(
                name="archunit_import",
                rules=[],
                source="archunit",
            )

        if not os.path.isfile(test_file):
            logger.warning(f"Test file not found: {test_file}")
            return RulePack(
                name="archunit_import",
                rules=[],
                source="archunit",
                metadata={"error": "file_not_found"},
            )

        try:
            content = open(test_file, "r", encoding="utf-8").read()

            # 简化解析——提取 ArchUnit 规则声明
            import re

            # 匹配 layeredArchitecture / noCycles / slices 等
            patterns = [
                # layeredArchitecture() 声明
                (r'layeredArchitecture\(\s*consideringAllPackages\(\)\s*\.layer\("(\w+)"\)\s*\.definedBy\("([^"]+)"\)', "layer_violation"),
                # noCycles() 声明
                (r'noCycles\(\s*([\w.]+)', "no_cycles"),
                # namingConvention 声明
                (r'namingConvention\(\s*([\w.]+)', "naming_convention"),
                # general @ArchTest 注解标记
                (r'@ArchTest\s+static\s+ArchRule\s+(\w+)\s*=\s*(.+?);', "general"),
            ]

            for pattern, check_type in patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    rule_name = match.group(1) if len(match.groups()) >= 1 else "unknown"
                    rule_detail = match.group(2) if len(match.groups()) >= 2 else ""

                    rule = ComplianceRule(
                        id=f"archunit_{check_type}_{rule_name}",
                        category=ComplianceCategory.ARCHITECTURE,
                        pattern=rule_detail[:100] if rule_detail else check_type,
                        severity="medium",
                        description=f"ArchUnit {check_type}: {rule_name}",
                        remediation=f"Fix ArchUnit {check_type} violations",
                        matcher_type="archunit",
                        matcher_config={
                            "check": check_type,
                            "test_file": test_file,
                            "rule_name": rule_name,
                        },
                    )
                    rules.append(rule)

        except Exception as e:
            logger.warning(f"ArchUnit rule import failed: {e}")
            return RulePack(
                name="archunit_import",
                rules=[],
                source="archunit",
                metadata={"error": str(e)},
            )

        return RulePack(
            name="archunit_import",
            rules=rules,
            source="archunit",
            metadata={
                "test_file": test_file,
                "imported": len(rules),
            },
        )

    def import_rules_from_config(
        self,
        config_file: Optional[str] = None,
    ) -> RulePack:
        """从 JSON 配置文件导入 ArchUnit 规则

        Args:
            config_file: JSON 配置文件路径

        Returns:
            RulePack 包含翻译后的 ComplianceRule 列表
        """
        if not config_file or not os.path.isfile(config_file):
            logger.warning(f"Config file not found: {config_file}")
            return RulePack(
                name="archunit_import",
                rules=[],
                source="archunit",
            )

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.loads(f.read())

            checks = config.get("checks", [])
            rules = []

            for check in checks:
                check_type = check.get("type", "layer_violation")
                name = check.get("name", f"archunit_{check_type}")

                rule = ComplianceRule(
                    id=f"archunit_{check_type}_{name}",
                    category=ComplianceCategory.ARCHITECTURE,
                    pattern=check_type,
                    severity=check.get("severity", "medium"),
                    description=check.get("description", f"ArchUnit {check_type} check: {name}"),
                    remediation=f"Fix ArchUnit {check_type} violations",
                    matcher_type="archunit",
                    matcher_config=check.get("config", {}),
                )
                rules.append(rule)

            return RulePack(
                name="archunit_import",
                rules=rules,
                source="archunit",
                metadata={
                    "config_file": config_file,
                    "imported": len(rules),
                },
            )

        except Exception as e:
            logger.warning(f"ArchUnit config import failed: {e}")
            return RulePack(
                name="archunit_import",
                rules=[],
                source="archunit",
                metadata={"error": str(e)},
            )


# ─── DepCruiserRuleImporter ────────────────────────────────────────


class DepCruiserRuleImporter:
    """DepCruiser 规则导入器

    从 .dependency-cruiser.js / .dependency-cruiser.json 配置文件
    解析依赖规则，翻译为 ComplianceRule 格式。

    用法：
        importer = DepCruiserRuleImporter()
        pack = importer.import_rules(
            config_file=".dependency-cruiser.js",
            project_root="/path/to/project",
        )
    """

    def import_rules(
        self,
        config_file: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> RulePack:
        """从 dependency-cruiser 配置文件导入规则

        Args:
            config_file: .dependency-cruiser.js / .dependency-cruiser.json 路径
            project_root: 项目根目录（自动查找配置文件）

        Returns:
            RulePack 包含翻译后的 ComplianceRule 列表
        """
        # 自动查找配置文件
        if not config_file and project_root:
            common_configs = [
                ".dependency-cruiser.json",
                ".dependency-cruiser.js",
                ".dependency-cruiser.cjs",
            ]
            for cfg in common_configs:
                cfg_path = os.path.join(project_root, cfg)
                if os.path.isfile(cfg_path):
                    config_file = cfg_path
                    break

        if not config_file or not os.path.isfile(config_file):
            logger.warning("dependency-cruiser config not found")
            return RulePack(
                name="dep_cruiser_import",
                rules=[],
                source="dep_cruiser",
            )

        # 只解析 JSON 格式（JS 格式需要 Node.js 执行）
        if config_file.endswith(".json"):
            return self._import_from_json(config_file)
        else:
            # JS 格式 → 尝试子进程解析
            return self._import_from_js(config_file)

    def _import_from_json(self, config_file: str) -> RulePack:
        """从 JSON 配置文件导入"""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.loads(f.read())

            # depcruise 配置中的 forbidden / allowed 规则
            forbidden = config.get("forbidden", [])
            allowed = config.get("allowed", [])

            rules = []

            # forbidden 规则
            for idx, rule_def in enumerate(forbidden):
                name = rule_def.get("name", f"forbidden_{idx}")
                comment = rule_def.get("comment", "")
                severity = rule_def.get("severity", "warn")

                # 映射 depcruise severity → harness severity
                severity_map = {
                    "error": "high",
                    "warn": "medium",
                    "info": "low",
                }
                mapped_severity = severity_map.get(severity, "medium")

                rule = ComplianceRule(
                    id=f"dep_cruiser_forbidden_{idx}",
                    category=ComplianceCategory.ARCHITECTURE,
                    pattern=name,
                    severity=mapped_severity,
                    description=comment or f"dependency-cruiser forbidden rule: {name}",
                    remediation=f"Fix dependency violation: {name}",
                    matcher_type="dep_cruiser",
                    matcher_config={
                        "check": "dependency_violation",
                        "cruise_config": config_file,
                        "rule_name": name,
                        "rule_type": "forbidden",
                    },
                )
                rules.append(rule)

            # allowed 规则（较少见，作为补充）
            for idx, rule_def in enumerate(allowed):
                name = rule_def.get("name", f"allowed_{idx}")
                comment = rule_def.get("comment", "")

                rule = ComplianceRule(
                    id=f"dep_cruiser_allowed_{idx}",
                    category=ComplianceCategory.ARCHITECTURE,
                    pattern=name,
                    severity="info",
                    description=comment or f"dependency-cruiser allowed rule: {name}",
                    remediation=f"Ensure dependency follows allowed pattern: {name}",
                    matcher_type="dep_cruiser",
                    matcher_config={
                        "check": "allowed_dependency",
                        "cruise_config": config_file,
                        "rule_name": name,
                        "rule_type": "allowed",
                    },
                )
                rules.append(rule)

            return RulePack(
                name="dep_cruiser_import",
                rules=rules,
                source="dep_cruiser",
                metadata={
                    "config_file": config_file,
                    "imported": len(rules),
                    "forbidden_count": len(forbidden),
                    "allowed_count": len(allowed),
                },
            )

        except Exception as e:
            logger.warning(f"DepCruiser JSON import failed: {e}")
            return RulePack(
                name="dep_cruiser_import",
                rules=[],
                source="dep_cruiser",
                metadata={"error": str(e)},
            )

    def _import_from_js(self, config_file: str) -> RulePack:
        """从 JS 配置文件导入（通过 Node.js 子进程）"""
        import subprocess

        try:
            # 尝试通过 Node.js 解析 JS 配置
            script = f"""
const config = require('{config_file}');
const output = {{
    forbidden: config.forbidden || [],
    allowed: config.allowed || [],
}};
console.log(JSON.stringify(output));
"""
            result = subprocess.run(
                ["node", "-e", script],
                capture_output=True, timeout=10, text=True,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                # 重新包装为带 forbidden/allowed 的格式
                return self._import_from_json_data(data, config_file)

            logger.warning(f"Node.js depcruise config parsing failed: {result.stderr}")
            return RulePack(
                name="dep_cruiser_import",
                rules=[],
                source="dep_cruiser",
                metadata={"error": "node_parse_failed"},
            )

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Node.js not available for JS config parsing: {e}")
            return RulePack(
                name="dep_cruiser_import",
                rules=[],
                source="dep_cruiser",
                metadata={"error": str(e)},
            )

    def _import_from_json_data(self, data: dict, config_file: str) -> RulePack:
        """从已解析的 JSON 数据导入（子进程路径的内部方法）"""
        forbidden = data.get("forbidden", [])
        allowed = data.get("allowed", [])

        rules = []
        severity_map = {"error": "high", "warn": "medium", "info": "low"}

        for idx, rule_def in enumerate(forbidden):
            name = rule_def.get("name", f"forbidden_{idx}")
            mapped_severity = severity_map.get(rule_def.get("severity", "warn"), "medium")

            rule = ComplianceRule(
                id=f"dep_cruiser_forbidden_{idx}",
                category=ComplianceCategory.ARCHITECTURE,
                pattern=name,
                severity=mapped_severity,
                description=rule_def.get("comment", f"dependency-cruiser forbidden: {name}"),
                remediation=f"Fix dependency violation: {name}",
                matcher_type="dep_cruiser",
                matcher_config={
                    "check": "dependency_violation",
                    "cruise_config": config_file,
                    "rule_name": name,
                },
            )
            rules.append(rule)

        return RulePack(
            name="dep_cruiser_import",
            rules=rules,
            source="dep_cruiser",
            metadata={
                "config_file": config_file,
                "imported": len(rules),
            },
        )
