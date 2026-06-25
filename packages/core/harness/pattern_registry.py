"""
PatternRegistry — 检测正则的统一定义源

所有治理层（护栏/合规/门禁）共享的正则检测模式注册表。
新增检测模式只需注册一个 PatternDefinition，各层按需获取。

设计原则：
1. 模式定义一次——同一正则不在多处重复定义
2. 各层共享同一源——护栏/合规/门禁从同一 Registry 获取模式
3. 各层按职责使用——获取模式后根据自身职责决定 severity/action
4. 新增只改一处——新增 PII 类型只需注册一个 PatternDefinition

迁移来源：
- 护栏层 PIIDetector.PATTERNS → PatternRegistry
- 合规层 security_rule_pack/privacy_rule_pack → PatternRegistry
- 门禁层 check_no_secrets/check_no_eval/check_no_sql_injection → PatternRegistry
"""

from __future__ import annotations

import re
from typing import Optional

from harness.types import (
    ComplianceCategory,
    ComplianceRule,
    PatternDefinition,
)


class PatternRegistry:
    """模式注册表——所有检测正则的唯一定义源

    用法:
        registry = get_pattern_registry()  # 获取全局实例

        # 按类别查询
        security_patterns = registry.get_by_category(ComplianceCategory.SECURITY)

        # 按目标类型查询
        pii_patterns = registry.get_by_target_type("pii")

        # 按 ID 获取
        pattern = registry.get("hardcoded-password")

        # 转换为 ComplianceRule
        rules = registry.to_compliance_rules(ComplianceCategory.SECURITY)
    """

    _instance: Optional[PatternRegistry] = None

    def __init__(self):
        self._patterns: dict[str, PatternDefinition] = {}
        self._compiled: dict[str, re.Pattern] = {}

    @classmethod
    def get_instance(cls) -> PatternRegistry:
        """获取全局单例——首次调用时自动注册内置模式"""
        if cls._instance is None:
            cls._instance = cls()
            _register_builtin_patterns(cls._instance)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置全局单例（测试用）"""
        cls._instance = None

    def register(self, pattern: PatternDefinition) -> None:
        """注册一个模式定义

        如果 id 已存在，覆盖旧定义。
        注册后自动编译正则表达式。
        """
        self._patterns[pattern.id] = pattern
        self._compiled[pattern.id] = re.compile(pattern.pattern, pattern.flags)

    def get(self, id: str) -> Optional[PatternDefinition]:
        """按 ID 获取模式定义"""
        return self._patterns.get(id)

    def get_compiled(self, id: str) -> Optional[re.Pattern]:
        """按 ID 获取编译后的正则"""
        return self._compiled.get(id)

    def get_by_category(self, category: ComplianceCategory) -> list[PatternDefinition]:
        """按类别获取所有模式"""
        return [p for p in self._patterns.values() if p.category == category]

    def get_by_target_type(self, target_type: str) -> list[PatternDefinition]:
        """按目标类型获取所有模式"""
        return [p for p in self._patterns.values() if p.target_type == target_type]

    def get_by_target_types(self, target_types: list[str]) -> list[PatternDefinition]:
        """按多个目标类型获取所有模式"""
        return [p for p in self._patterns.values() if p.target_type in target_types]

    def get_by_sub_type(self, sub_type: str) -> list[PatternDefinition]:
        """按子类型获取所有模式"""
        return [p for p in self._patterns.values() if p.sub_type == sub_type]

    def all_patterns(self) -> list[PatternDefinition]:
        """获取所有已注册的模式"""
        return list(self._patterns.values())

    def match(self, content: str,
              target_type: str = None,
              category: ComplianceCategory = None) -> list[tuple[PatternDefinition, list[re.Match]]]:
        """在内容中匹配模式

        返回 (PatternDefinition, [Match对象]) 列表。
        可按 target_type 或 category 过滤。
        """
        results = []
        patterns = list(self._patterns.values())
        if target_type:
            patterns = [p for p in patterns if p.target_type == target_type]
        if category:
            patterns = [p for p in patterns if p.category == category]

        for p in patterns:
            compiled = self._compiled.get(p.id)
            if compiled:
                matches = list(compiled.finditer(content))
                if matches:
                    results.append((p, matches))

        return results

    def to_compliance_rule(self, pattern: PatternDefinition) -> ComplianceRule:
        """将 PatternDefinition 转换为 ComplianceRule

        PatternDefinition 是"检测什么"的唯一定义，
        ComplianceRule 是"如何合规检查"的使用方式。
        此方法做一层标准化转换。
        """
        return ComplianceRule(
            id=pattern.id,
            category=pattern.category,
            pattern=pattern.pattern,
            severity=pattern.canonical_severity,
            description=pattern.description,
            remediation=pattern.remediation,
            languages=pattern.languages,
            matcher_type="regex",
        )

    def to_compliance_rules(self,
                            category: ComplianceCategory = None,
                            target_type: str = None) -> list[ComplianceRule]:
        """批量转换为 ComplianceRule

        可按 category 或 target_type 过滤。
        不传过滤条件则转换所有模式。
        """
        patterns = list(self._patterns.values())
        if category:
            patterns = [p for p in patterns if p.category == category]
        if target_type:
            patterns = [p for p in patterns if p.target_type == target_type]
        return [self.to_compliance_rule(p) for p in patterns]


def get_pattern_registry() -> PatternRegistry:
    """获取全局 PatternRegistry 单例"""
    return PatternRegistry.get_instance()


# ═══════════════════════════════════════════════════════════════
#  内置模式注册——从三层迁移合并的统一定义
# ═══════════════════════════════════════════════════════════════

def _register_builtin_patterns(registry: PatternRegistry) -> None:
    """注册所有内置模式——合并护栏/合规/门禁三层的定义

    正则统一原则：
    - 同一检测目标使用同一正则（不再有三层各自不同阈值的问题）
    - 优先采用更精确的版本（门禁 SQL 注入要求 FROM/INTO/SET 关键字）
    - 优先采用更全面的版本（合规 sec-hardcoded-secret 合并了所有关键字）
    - 阈值统一为 8（平衡护栏的宽松阈值 6 和门禁的严格阈值 16）

    severity 统一原则：
    - canonical_severity 采用最常用的 severity（合规/门禁的 critical）
    - 护栏层自行决定是否覆盖为 warning（这是护栏的职责，不是模式定义的职责）
    """

    # ─── SECRET — 硬编码凭据/密钥 ───

    # 硬编码密码（合并护栏/合规/门禁的 password 模式，阈值统一 8）
    # 来源：guardrails PIIDetector.password(阈值6) + compliance sec-hardcoded-secret(阈值8) + gates(阈值8)
    registry.register(PatternDefinition(
        id="hardcoded-password",
        pattern=r'(?:password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']',
        category=ComplianceCategory.SECURITY,
        target_type="secret",
        canonical_severity="critical",
        sub_type="password",
        description="硬编码密码——代码中直接写入密码值",
        remediation="使用环境变量或配置文件存储密码，不要硬编码在源码中",
        languages=["python", "javascript", "typescript", "go", "java", "ruby"],
        flags=re.IGNORECASE,
    ))

    # 硬编码 API 密钥（合并护栏/合规/门禁，阈值统一 8）
    # 来源：guardrails PIIDetector.api_key_generic(阈值8) + compliance sec-hardcoded-secret(合并版) + gates(阈值16→统一8)
    registry.register(PatternDefinition(
        id="hardcoded-api-key",
        pattern=r'(?:api_key|apikey|access_key|secret_key)\s*[:=]\s*["\'][^"\']{8,}["\']',
        category=ComplianceCategory.SECURITY,
        target_type="secret",
        canonical_severity="critical",
        sub_type="api_key",
        description="硬编码 API 密钥——代码中直接写入 API 密钥值",
        remediation="使用环境变量或密钥管理服务存储 API 密钥",
        languages=["python", "javascript", "typescript", "go", "java", "ruby"],
        flags=re.IGNORECASE,
    ))

    # 硬编码 secret/token（合并护栏/合规/门禁，阈值统一 8）
    # 来源：guardrails PIIDetector.token(阈值8) + compliance sec-hardcoded-secret(合并版) + gates(阈值16→统一8)
    registry.register(PatternDefinition(
        id="hardcoded-secret-token",
        pattern=r'(?:secret|token|auth_token|bearer)\s*[:=]\s*["\'][^"\']{8,}["\']',
        category=ComplianceCategory.SECURITY,
        target_type="secret",
        canonical_severity="critical",
        sub_type="token",
        description="硬编码 secret/token——代码中直接写入认证令牌",
        remediation="使用环境变量或密钥管理服务存储认证令牌",
        languages=["python", "javascript", "typescript", "go", "java", "ruby"],
        flags=re.IGNORECASE,
    ))

    # OpenAI API 密钥（合并合规/门禁，护栏新增覆盖）
    # 来源：compliance sec-openai-key + gates check_no_secrets（正则完全相同）
    registry.register(PatternDefinition(
        id="openai-api-key",
        pattern=r'sk-[a-zA-Z0-9]{32,}',
        category=ComplianceCategory.SECURITY,
        target_type="secret",
        canonical_severity="critical",
        sub_type="openai_key",
        description="OpenAI API 密钥暴露——sk- 开头的密钥字符串",
        remediation="立即撤销泄露的密钥，使用环境变量存储新密钥",
    ))

    # GitHub Token（合并合规/门禁，护栏新增覆盖）
    # 来源：compliance sec-github-token + gates check_no_secrets（正则完全相同）
    registry.register(PatternDefinition(
        id="github-token",
        pattern=r'ghp_[a-zA-Z0-9]{36}',
        category=ComplianceCategory.SECURITY,
        target_type="secret",
        canonical_severity="critical",
        sub_type="github_token",
        description="GitHub Personal Access Token 暴露——ghp_ 开头的令牌",
        remediation="立即撤销泄露的令牌，使用环境变量存储新令牌",
    ))

    # ─── PII — 个人隐私信息 ───

    # Email 地址（合并护栏/合规）
    # 来源：guardrails PIIDetector.email + compliance priv-email-exposure（正则完全相同）
    registry.register(PatternDefinition(
        id="pii-email",
        pattern=r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="medium",
        sub_type="email",
        description="Email 地址暴露——代码或输出中包含电子邮箱地址",
        remediation="使用脱敏处理或用户 ID 替代直接使用 Email 地址",
    ))

    # 美国电话号码（从护栏迁移）
    # 来源：guardrails PIIDetector.phone_us
    registry.register(PatternDefinition(
        id="pii-phone-us",
        pattern=r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="medium",
        sub_type="phone_us",
        description="美国电话号码暴露——10位数字电话号码",
        remediation="使用脱敏处理替代直接使用电话号码",
    ))

    # 国际电话号码（从护栏迁移，合并合规的括号格式支持）
    # 来源：guardrails PIIDetector.phone_intl + compliance priv-phone-exposure（合并版更通用）
    registry.register(PatternDefinition(
        id="pii-phone-intl",
        pattern=r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="medium",
        sub_type="phone_intl",
        description="国际电话号码暴露——含国际区号的电话号码",
        remediation="使用脱敏处理替代直接使用电话号码",
    ))

    # 美国社会安全号（从护栏迁移，合规新增覆盖）
    # 来源：guardrails PIIDetector.ssn
    registry.register(PatternDefinition(
        id="pii-ssn",
        pattern=r'\b\d{3}-\d{2}-\d{4}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="critical",
        sub_type="ssn",
        description="美国社会安全号(SSN)暴露——XXX-XX-XXXX 格式",
        remediation="SSN 属于高度敏感信息，严禁出现在代码或输出中",
    ))

    # 信用卡号（从护栏迁移，合规新增覆盖）
    # 来源：guardrails PIIDetector.credit_card
    registry.register(PatternDefinition(
        id="pii-credit-card",
        pattern=r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="critical",
        sub_type="credit_card",
        description="信用卡号暴露——16位数字信用卡号码",
        remediation="信用卡号属于高度敏感信息，严禁出现在代码或输出中",
    ))

    # 所有 IP 地址（从护栏迁移，保留全 IP 覆盖）
    # 来源：guardrails PIIDetector.ip_address（覆盖全部 IP）
    registry.register(PatternDefinition(
        id="pii-ip-address",
        pattern=r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="low",
        sub_type="ip_address",
        description="IP 地址暴露——代码或输出中包含 IP 地址",
        remediation="使用域名替代 IP 地址，或使用配置文件管理",
    ))

    # 内网 IP 地址（从合规迁移，专门检测 RFC1918 内网 IP）
    # 来源：compliance priv-ip-exposure（仅覆盖 RFC1918 私有地址段）
    # 注：与 pii-ip-address 互补——pii-ip-address 覆盖全部 IP，pii-ip-private 仅覆盖内网
    registry.register(PatternDefinition(
        id="pii-ip-private",
        pattern=r'\b(?:192\.168|10\.|172\.(?:1[6-9]|2[0-9]|3[01]))\.\d{1,3}\.\d{1,3}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="medium",
        sub_type="ip_private",
        description="内网 IP 地址暴露——RFC1918 私有地址段",
        remediation="内网 IP 泄露可能暴露内部网络拓扑，使用配置管理",
    ))

    # 中国身份证号（从护栏迁移，合规新增覆盖）
    # 来源：guardrails PIIDetector.id_card_cn
    registry.register(PatternDefinition(
        id="pii-id-card-cn",
        pattern=r'\b\d{17}[\dXx]\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="critical",
        sub_type="id_card_cn",
        description="中国身份证号暴露——18位身份证号码",
        remediation="中国身份证号属于高度敏感个人信息，严禁出现在代码或输出中",
    ))

    # 中国手机号（从护栏迁移，合规新增覆盖）
    # 来源：guardrails PIIDetector.phone_cn
    registry.register(PatternDefinition(
        id="pii-phone-cn",
        pattern=r'\b1[3-9]\d{9}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="high",
        sub_type="phone_cn",
        description="中国手机号暴露——11位手机号码",
        remediation="使用脱敏处理替代直接使用手机号",
    ))

    # 中国银行卡号（从护栏迁移，合规新增覆盖）
    # 来源：guardrails PIIDetector.bank_card_cn
    # ⚠️ 注意：此模式较宽泛，可能匹配任意 16-19 位数字串，需结合上下文判断
    registry.register(PatternDefinition(
        id="pii-bank-card-cn",
        pattern=r'\b\d{16,19}\b',
        category=ComplianceCategory.PRIVACY,
        target_type="pii",
        canonical_severity="critical",
        sub_type="bank_card_cn",
        description="中国银行卡号暴露——16-19位银行卡号",
        remediation="银行卡号属于高度敏感信息，严禁出现在代码或输出中",
    ))

    # ─── CODE_INJECTION — 代码注入风险 ───

    # eval() 调用（合并护栏/合规/门禁）
    # 来源：guardrails OutputGuardrails + compliance sec-eval-usage + gates check_no_eval（正则完全相同）
    # 注：护栏层将其视为 warning，合规/门禁视为 critical——这是各层的职责决策，不影响模式定义
    registry.register(PatternDefinition(
        id="code-injection-eval",
        pattern=r'\beval\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="critical",
        sub_type="eval",
        description="eval() 代码注入风险——动态执行字符串代码",
        remediation="避免使用 eval()，使用 ast.literal_eval() 或安全的解析方法替代",
        languages=["python"],
    ))

    # exec() 调用（合并护栏/合规/门禁）
    # 来源：同 eval()，三层正则相同，severity 差异由各层自行决定
    registry.register(PatternDefinition(
        id="code-injection-exec",
        pattern=r'\bexec\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="critical",
        sub_type="exec",
        description="exec() 任意代码执行风险——动态执行 Python 代码",
        remediation="避免使用 exec()，重构代码使用安全的替代方案",
        languages=["python"],
    ))

    # compile() 调用（从门禁迁移）
    # 来源：gates check_no_eval（独有的 compile 检测）
    registry.register(PatternDefinition(
        id="code-injection-compile",
        pattern=r'\bcompile\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="high",
        sub_type="compile",
        description="compile() 代码编译风险——动态编译字符串为代码对象",
        remediation="避免使用 compile() 配合 eval/exec，使用静态代码替代",
        languages=["python"],
    ))

    # __import__() 调用（从护栏迁移）
    # 来源：guardrails OutputGuardrails.unsafe_patterns
    registry.register(PatternDefinition(
        id="code-injection-import",
        pattern=r'\b__import__\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="high",
        sub_type="import",
        description="__import__() 动态导入风险——运行时动态导入模块",
        remediation="使用 importlib.import_module() 替代 __import__()",
        languages=["python"],
    ))

    # os.system() 调用（从护栏迁移）
    # 来源：guardrails OutputGuardrails.unsafe_patterns
    registry.register(PatternDefinition(
        id="code-injection-os-system",
        pattern=r'\bos\.system\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="high",
        sub_type="os_system",
        description="os.system() 命令执行风险——直接执行系统命令",
        remediation="使用 subprocess.run() 替代 os.system()，避免 shell 注入",
        languages=["python"],
    ))

    # subprocess shell=True（从护栏迁移）
    # 来源：guardrails OutputGuardrails.unsafe_patterns
    registry.register(PatternDefinition(
        id="code-injection-subprocess-shell",
        pattern=r'\bsubprocess\.call\s*\(.*shell=True',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="high",
        sub_type="subprocess_shell",
        description="subprocess shell=True 命令注入风险——通过 shell 执行命令",
        remediation="使用 subprocess.run() 且 shell=False，传递参数列表而非字符串",
        languages=["python"],
    ))

    # pickle.loads() 反序列化（从护栏迁移）
    # 来源：guardrails OutputGuardrails.unsafe_patterns
    registry.register(PatternDefinition(
        id="code-injection-pickle",
        pattern=r'\bpickle\.loads\s*\(',
        category=ComplianceCategory.SECURITY,
        target_type="code_injection",
        canonical_severity="high",
        sub_type="pickle",
        description="pickle.loads() 反序列化风险——可能导致任意代码执行",
        remediation="使用 JSON 或其他安全的序列化格式替代 pickle",
        languages=["python"],
    ))

    # ─── SQL_INJECTION — SQL 注入 ───

    # f-string SQL SELECT 注入（改进版——变量插值可在 SELECT 前后任意位置）
    # 来源：compliance sec-sql-injection-fstring(合并版) + gates check_no_sql_injection(精确版)
    # 改进：原版要求 {var} 在 FROM/INTO/SET 关键字之前，漏检了 "{var} 在关键字之后" 的常见场景
    # 新版只需 f-string 中同时出现 SQL 关键字 + 变量插值，不要求特定顺序
    registry.register(PatternDefinition(
        id="sql-injection-fstring-select",
        pattern=r'f["\'].*SELECT.*\{.*\}',
        category=ComplianceCategory.SECURITY,
        target_type="sql_injection",
        canonical_severity="high",
        sub_type="fstring_select",
        description="f-string SQL SELECT 注入——使用 f-string 构建 SQL SELECT 语句",
        remediation="使用参数化查询替代 f-string 构建 SQL 语句",
        languages=["python"],
        flags=re.IGNORECASE | re.DOTALL,
    ))

    # f-string SQL INSERT 注入（改进版——变量插值可在 INSERT 前后任意位置）
    registry.register(PatternDefinition(
        id="sql-injection-fstring-insert",
        pattern=r'f["\'].*INSERT.*\{.*\}',
        category=ComplianceCategory.SECURITY,
        target_type="sql_injection",
        canonical_severity="high",
        sub_type="fstring_insert",
        description="f-string SQL INSERT 注入——使用 f-string 构建 SQL INSERT 语句",
        remediation="使用参数化查询替代 f-string 构建 SQL 语句",
        languages=["python"],
        flags=re.IGNORECASE | re.DOTALL,
    ))

    # f-string SQL UPDATE 注入（改进版——变量插值可在 UPDATE 前后任意位置）
    registry.register(PatternDefinition(
        id="sql-injection-fstring-update",
        pattern=r'f["\'].*UPDATE.*\{.*\}',
        category=ComplianceCategory.SECURITY,
        target_type="sql_injection",
        canonical_severity="high",
        sub_type="fstring_update",
        description="f-string SQL UPDATE 注入——使用 f-string 构建 SQL UPDATE 语句",
        remediation="使用参数化查询替代 f-string 构建 SQL 语句",
        languages=["python"],
        flags=re.IGNORECASE | re.DOTALL,
    ))

    # f-string SQL DELETE 注入（改进版——变量插值可在 DELETE 前后任意位置）
    registry.register(PatternDefinition(
        id="sql-injection-fstring-delete",
        pattern=r'f["\'].*DELETE.*\{.*\}',
        category=ComplianceCategory.SECURITY,
        target_type="sql_injection",
        canonical_severity="high",
        sub_type="fstring_delete",
        description="f-string SQL DELETE 注入——使用 f-string 构建 SQL DELETE 语句",
        remediation="使用参数化查询替代 f-string 构建 SQL 语句",
        languages=["python"],
        flags=re.IGNORECASE | re.DOTALL,
    ))

    # 字符串拼接 SQL 注入（从门禁迁移）
    # 来源：gates check_no_sql_injection（独有的拼接注入检测）
    registry.register(PatternDefinition(
        id="sql-injection-concat",
        pattern=r'\+\s*["\'].*SELECT',
        category=ComplianceCategory.SECURITY,
        target_type="sql_injection",
        canonical_severity="high",
        sub_type="concat",
        description="字符串拼接 SQL 注入——使用 + 拼接构建 SQL 语句",
        remediation="使用参数化查询替代字符串拼接构建 SQL 语句",
        languages=["python"],
        flags=re.IGNORECASE | re.DOTALL,
    ))

    # ─── OTHER — 其他安全风险 ───

    # ReDoS 风险正则（从合规迁移）
    # 来源：compliance sec-unsafe-regex
    registry.register(PatternDefinition(
        id="unsafe-regex-redos",
        pattern=r're\.compile\s*\([^)]*(?:\(\?\:|\\\d{10,}|[a-z0-9]{100,})',
        category=ComplianceCategory.SECURITY,
        target_type="unsafe_code",
        canonical_severity="medium",
        sub_type="redos",
        description="ReDoS 风险正则——可能导致正则表达式拒绝服务攻击",
        remediation="避免嵌套量词和回溯风险的正则模式，使用原子组或超时机制",
        languages=["python"],
    ))

    # HTTP 敏感端点（从合规迁移）
    # 来源：compliance sec-http-only-url
    registry.register(PatternDefinition(
        id="http-sensitive-endpoint",
        pattern=r'http://[^\s"\']+(?:api|login|auth|token|secret|key)',
        category=ComplianceCategory.SECURITY,
        target_type="unsafe_code",
        canonical_severity="high",
        sub_type="http_endpoint",
        description="HTTP 敏感端点——使用不加密的 HTTP 协议访问敏感资源",
        remediation="使用 HTTPS 替代 HTTP，确保所有敏感端点使用加密传输",
    ))
