"""
Phase 7 测试: 内置规则包（coding/security/data/devops）

测试覆盖:
- 每个pack的规则数量和ID格式
- 每个pack的category正确性
- ComplianceEngine加载pack + scan_basic测试（验证规则能检测已知违规）
- pack工厂函数返回类型
"""

from __future__ import annotations

from harness.types import (
    Artifact,
    ComplianceCategory,
    ComplianceRule,
    ComplianceResult,
)
from harness.compliance import ComplianceEngine, RulePack
from harness.bus import EventBus
from harness.rule_packs import (
    get_coding_pack,
    get_security_pack,
    get_data_pack,
    get_devops_pack,
)


# ═══════════════════════════════════════════════════════════
#  Pack Factory Tests
# ═══════════════════════════════════════════════════════════

class TestCodingPackFactory:
    """Coding pack 工厂函数测试"""

    def test_returns_rule_pack(self):
        pack = get_coding_pack()
        assert isinstance(pack, RulePack)

    def test_pack_name(self):
        pack = get_coding_pack()
        assert pack.name == "coding"

    def test_pack_category(self):
        pack = get_coding_pack()
        assert pack.category == ComplianceCategory.STYLE

    def test_minimum_rules(self):
        pack = get_coding_pack()
        assert len(pack.rules) >= 6

    def test_rule_id_prefix(self):
        pack = get_coding_pack()
        for rule in pack.rules:
            assert rule.id.startswith("CODE-"), f"Rule ID '{rule.id}' should start with 'CODE-'"

    def test_all_rules_style_category(self):
        pack = get_coding_pack()
        for rule in pack.rules:
            assert rule.category == ComplianceCategory.STYLE, f"Rule '{rule.id}' should be STYLE"


class TestSecurityPackFactory:
    """Security pack 工厂函数测试"""

    def test_returns_rule_pack(self):
        pack = get_security_pack()
        assert isinstance(pack, RulePack)

    def test_pack_name(self):
        pack = get_security_pack()
        assert pack.name == "security"

    def test_pack_category(self):
        pack = get_security_pack()
        assert pack.category == ComplianceCategory.SECURITY

    def test_minimum_rules(self):
        pack = get_security_pack()
        assert len(pack.rules) >= 6

    def test_rule_id_prefix(self):
        pack = get_security_pack()
        for rule in pack.rules:
            assert rule.id.startswith("SEC-"), f"Rule ID '{rule.id}' should start with 'SEC-'"

    def test_all_rules_security_category(self):
        pack = get_security_pack()
        for rule in pack.rules:
            assert rule.category == ComplianceCategory.SECURITY, f"Rule '{rule.id}' should be SECURITY"


class TestDataPackFactory:
    """Data/privacy pack 工厂函数测试"""

    def test_returns_rule_pack(self):
        pack = get_data_pack()
        assert isinstance(pack, RulePack)

    def test_pack_name(self):
        pack = get_data_pack()
        assert pack.name == "data"

    def test_pack_category(self):
        pack = get_data_pack()
        assert pack.category == ComplianceCategory.PRIVACY

    def test_minimum_rules(self):
        pack = get_data_pack()
        assert len(pack.rules) >= 6

    def test_rule_id_prefix(self):
        pack = get_data_pack()
        for rule in pack.rules:
            assert rule.id.startswith("DATA-"), f"Rule ID '{rule.id}' should start with 'DATA-'"

    def test_all_rules_privacy_category(self):
        pack = get_data_pack()
        for rule in pack.rules:
            assert rule.category == ComplianceCategory.PRIVACY, f"Rule '{rule.id}' should be PRIVACY"


class TestDevopsPackFactory:
    """DevOps pack 工厂函数测试"""

    def test_returns_rule_pack(self):
        pack = get_devops_pack()
        assert isinstance(pack, RulePack)

    def test_pack_name(self):
        pack = get_devops_pack()
        assert pack.name == "devops"

    def test_pack_category(self):
        pack = get_devops_pack()
        assert pack.category == ComplianceCategory.ARCHITECTURE

    def test_minimum_rules(self):
        pack = get_devops_pack()
        assert len(pack.rules) >= 6

    def test_rule_id_prefix(self):
        pack = get_devops_pack()
        for rule in pack.rules:
            assert rule.id.startswith("OPS-"), f"Rule ID '{rule.id}' should start with 'OPS-'"

    def test_all_rules_architecture_category(self):
        pack = get_devops_pack()
        for rule in pack.rules:
            assert rule.category == ComplianceCategory.ARCHITECTURE, f"Rule '{rule.id}' should be ARCHITECTURE"


# ═══════════════════════════════════════════════════════════
#  ComplianceEngine + Pack Integration Tests
# ═══════════════════════════════════════════════════════════

class TestCodingPackScan:
    """Coding pack + engine scan测试"""

    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(get_coding_pack())

    def test_detect_todo_comment(self):
        """CODE-004 应检测 TODO 注释"""
        artifact = Artifact(type="code", path="todo.py", content="# TODO fix this later\nx = 1")
        results = self.engine.scan([artifact])
        todo_result = [r for r in results if r.rule_id == "CODE-004"]
        assert len(todo_result) > 0
        assert not todo_result[0].passed

    def test_detect_empty_except(self):
        """CODE-005 应检测空except块"""
        artifact = Artifact(type="code", path="empty_except.py",
                           content="try:\n    x = 1\nexcept ValueError:\n    pass\n")
        results = self.engine.scan([artifact])
        except_result = [r for r in results if r.rule_id == "CODE-005"]
        assert len(except_result) > 0
        assert not except_result[0].passed

    def test_clean_code_passes(self):
        """干净的代码应通过大部分coding规则"""
        artifact = Artifact(type="code", path="clean.py",
                           content="def hello_world():\n    return 'hello'\n")
        results = self.engine.scan([artifact])
        passed_ids = [r.rule_id for r in results if r.passed]
        assert "CODE-004" in passed_ids
        assert "CODE-005" in passed_ids


class TestSecurityPackScan:
    """Security pack + engine scan测试"""

    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(get_security_pack())

    def test_detect_hardcoded_secret(self):
        """SEC-001 应检测硬编码密钥"""
        artifact = Artifact(type="code", path="secret.py",
                           content="api_key = 'my_super_secret_key_12345'")
        results = self.engine.scan([artifact])
        secret_result = [r for r in results if r.rule_id == "SEC-001"]
        assert len(secret_result) > 0
        assert not secret_result[0].passed

    def test_detect_command_injection(self):
        """SEC-007 应检测命令注入"""
        artifact = Artifact(type="code", path="inject.py",
                           content="os.system('rm -rf ' + user_input)")
        results = self.engine.scan([artifact])
        cmd_result = [r for r in results if r.rule_id == "SEC-007"]
        assert len(cmd_result) > 0
        assert not cmd_result[0].passed

    def test_detect_path_traversal(self):
        """SEC-006 应检测路径遍历"""
        artifact = Artifact(type="code", path="traversal.py",
                           content="open('../../../etc/passwd')")
        results = self.engine.scan([artifact])
        traversal_result = [r for r in results if r.rule_id == "SEC-006"]
        assert len(traversal_result) > 0
        assert not traversal_result[0].passed

    def test_detect_http_sensitive_endpoint(self):
        """SEC-004 应检测HTTP敏感端点"""
        artifact = Artifact(type="code", path="http.py",
                           content="url = 'http://api.login.example.com/auth'")
        results = self.engine.scan([artifact])
        http_result = [r for r in results if r.rule_id == "SEC-004"]
        assert len(http_result) > 0
        assert not http_result[0].passed

    def test_clean_code_passes(self):
        """干净代码应通过所有security规则"""
        artifact = Artifact(type="code", path="safe.py", content="x = 1 + 2\ny = x * 3\n")
        results = self.engine.scan([artifact])
        violations = [r for r in results if not r.passed]
        assert len(violations) == 0


class TestDataPackScan:
    """Data pack + engine scan测试"""

    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(get_data_pack())

    def test_detect_email_exposure(self):
        """DATA-001 应检测邮件地址泄露"""
        artifact = Artifact(type="code", path="email.py",
                           content="admin_email = 'admin@company.com'")
        results = self.engine.scan([artifact])
        email_result = [r for r in results if r.rule_id == "DATA-001"]
        assert len(email_result) > 0
        assert not email_result[0].passed

    def test_detect_ssn_exposure(self):
        """DATA-003 应检测SSN泄露"""
        artifact = Artifact(type="code", path="ssn.py",
                           content="ssn = '123-45-6789'")
        results = self.engine.scan([artifact])
        ssn_result = [r for r in results if r.rule_id == "DATA-003"]
        assert len(ssn_result) > 0
        assert not ssn_result[0].passed

    def test_detect_logging_privacy(self):
        """DATA-005 应检测敏感数据日志记录"""
        artifact = Artifact(type="code", path="logging.py",
                           content="logger.info('User password is abc123')")
        results = self.engine.scan([artifact])
        log_result = [r for r in results if r.rule_id == "DATA-005"]
        assert len(log_result) > 0
        assert not log_result[0].passed

    def test_detect_data_classification(self):
        """DATA-004 应检测数据分类标记"""
        artifact = Artifact(type="code", path="classified.py",
                           content="CONFIDENTIAL: project data")
        results = self.engine.scan([artifact])
        class_result = [r for r in results if r.rule_id == "DATA-004"]
        assert len(class_result) > 0
        assert not class_result[0].passed

    def test_clean_code_passes(self):
        """干净代码不应触发大部分data规则"""
        artifact = Artifact(type="code", path="clean.py",
                           content="x = 42\nname = 'test'\nresult = x + name\n")
        results = self.engine.scan([artifact])
        passed_ids = [r.rule_id for r in results if r.passed]
        assert "DATA-003" in passed_ids
        assert "DATA-005" in passed_ids


class TestDevopsPackScan:
    """DevOps pack + engine scan测试"""

    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(get_devops_pack())

    def test_detect_docker_root_user(self):
        """OPS-005 应检测 Docker root 用户"""
        artifact = Artifact(type="code", path="Dockerfile",
                           content="FROM python:3.9\nUSER root\nRUN pip install app\n")
        results = self.engine.scan([artifact])
        root_result = [r for r in results if r.rule_id == "OPS-005"]
        assert len(root_result) > 0
        assert not root_result[0].passed

    def test_detect_unpinned_dependency(self):
        """OPS-006 应检测未固定的依赖"""
        artifact = Artifact(type="code", path="Dockerfile",
                           content="FROM python:latest\nRUN pip install app\n")
        results = self.engine.scan([artifact])
        pin_result = [r for r in results if r.rule_id == "OPS-006"]
        assert len(pin_result) > 0
        assert not pin_result[0].passed

    def test_detect_hardcoded_env_secret(self):
        """OPS-004 应检测硬编码的环境变量"""
        artifact = Artifact(type="code", path="docker-compose.yaml",
                           content="ENV {password: 'mysecretpass123', api_key: 'key456'}")
        results = self.engine.scan([artifact])
        env_result = [r for r in results if r.rule_id == "OPS-004"]
        assert len(env_result) > 0
        assert not env_result[0].passed

    def test_detect_empty_ci_field(self):
        """OPS-001 应检测空的CI配置字段"""
        artifact = Artifact(type="code", path=".gitlab-ci.yml",
                           content="name:\nscript:\nstages:\n")
        results = self.engine.scan([artifact])
        ci_result = [r for r in results if r.rule_id == "OPS-001"]
        assert len(ci_result) > 0
        assert not ci_result[0].passed

    def test_clean_config_passes(self):
        """干净的配置应通过OPS-001"""
        artifact = Artifact(type="code", path="clean.yaml",
                           content="name: my-app\nscript: echo hello\n")
        results = self.engine.scan([artifact])
        ops001_result = [r for r in results if r.rule_id == "OPS-001"]
        assert len(ops001_result) > 0
        assert ops001_result[0].passed


class TestAllPacksLoadedTogether:
    """同时加载所有4个pack的集成测试"""

    def setup_method(self):
        self.engine = ComplianceEngine(bus=EventBus())
        self.engine.load_pack(get_coding_pack())
        self.engine.load_pack(get_security_pack())
        self.engine.load_pack(get_data_pack())
        self.engine.load_pack(get_devops_pack())

    def test_all_packs_loaded(self):
        """所有4个pack都应成功加载（E-6 移除 learned-rules 自动注册路径，不再有 learned-rules 包）"""
        assert len(self.engine.list_packs()) == 4
        assert "coding" in self.engine.list_packs()
        assert "security" in self.engine.list_packs()
        assert "data" in self.engine.list_packs()
        assert "devops" in self.engine.list_packs()

    def test_total_rules_count(self):
        """总规则数应 >= 24 (4 packs × 6 rules minimum)"""
        stats = self.engine.stats()
        assert stats["total_rules"] >= 24

    def test_scan_with_all_packs(self):
        """使用所有pack扫描一个有违规的文件"""
        artifact = Artifact(type="code", path="bad.py",
                           content="# TODO fix this\napi_key = 'supersecret12345'\nadmin@company.com\n")
        results = self.engine.scan([artifact])
        violations = [r for r in results if not r.passed]
        # Should detect: TODO (CODE-004), hardcoded secret (SEC-001), email (DATA-001)
        assert len(violations) >= 3

    def test_scan_clean_with_all_packs(self):
        """使用所有pack扫描干净文件 — 大部分规则应通过"""
        artifact = Artifact(type="code", path="good.py",
                           content="def calculate(x, y):\n    return x + y\n")
        results = self.engine.scan([artifact])
        passed = sum(1 for r in results if r.passed)
        assert passed > len(results) // 2


class TestRuleProperties:
    """规则属性完整性测试"""

    def test_coding_rules_have_required_fields(self):
        pack = get_coding_pack()
        for rule in pack.rules:
            assert rule.id, "Rule must have an ID"
            assert rule.category == ComplianceCategory.STYLE
            assert rule.pattern, "Rule must have a pattern"
            assert rule.severity in ("critical", "high", "medium", "low")
            assert rule.description, "Rule must have a description"
            assert rule.remediation, "Rule must have a remediation"

    def test_security_rules_have_required_fields(self):
        pack = get_security_pack()
        for rule in pack.rules:
            assert rule.id, "Rule must have an ID"
            assert rule.category == ComplianceCategory.SECURITY
            assert rule.pattern, "Rule must have a pattern"
            assert rule.severity in ("critical", "high", "medium", "low")
            assert rule.description, "Rule must have a description"
            assert rule.remediation, "Rule must have a remediation"

    def test_data_rules_have_required_fields(self):
        pack = get_data_pack()
        for rule in pack.rules:
            assert rule.id, "Rule must have an ID"
            assert rule.category == ComplianceCategory.PRIVACY
            assert rule.pattern, "Rule must have a pattern"
            assert rule.severity in ("critical", "high", "medium", "low")
            assert rule.description, "Rule must have a description"
            assert rule.remediation, "Rule must have a remediation"

    def test_devops_rules_have_required_fields(self):
        pack = get_devops_pack()
        for rule in pack.rules:
            assert rule.id, "Rule must have an ID"
            assert rule.category == ComplianceCategory.ARCHITECTURE
            assert rule.pattern, "Rule must have a pattern"
            assert rule.severity in ("critical", "high", "medium", "low")
            assert rule.description, "Rule must have a description"
            assert rule.remediation, "Rule must have a remediation"