"""
harness-cook 自定义异常类型体系

所有异常继承自 HarnessError 基类，提供结构化错误信息（message/code/context/detail）。
每个子类对应一个领域错误场景，默认 code 可在实例化时覆盖。
不依赖其他 harness 模块，避免循环依赖。
"""


class HarnessError(Exception):
    """Harness 框架异常基类"""

    def __init__(
        self,
        message: str,
        code: str = "HARNESS_ERROR",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or {}
        self.detail = detail

    def to_dict(self) -> dict:
        """结构化输出，便于 JSON 日志和 API 响应"""
        return {
            "error": self.code,
            "message": self.message,
            "detail": self.detail,
            "context": self.context,
        }

    def __str__(self):
        if self.detail:
            return f"[{self.code}] {self.message} — {self.detail}"
        return f"[{self.code}] {self.message}"

    def __repr__(self):
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


# ── 领域异常子类 ──────────────────────────────────────────────


class ConstraintViolationError(HarnessError):
    """约束违规 — Agent 突破文件/命令白名单等约束边界"""

    def __init__(
        self,
        message: str,
        code: str = "CONSTRAINT_VIOLATION",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class GateCheckError(HarnessError):
    """门禁检查失败 — Gate 检查项不通过"""

    def __init__(
        self,
        message: str,
        code: str = "GATE_CHECK_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class SkillExecutionError(HarnessError):
    """Skill 执行失败 — Skill 运行时异常"""

    def __init__(
        self,
        message: str,
        code: str = "SKILL_EXECUTION_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class ProfileLoadError(HarnessError):
    """Profile 加载失败 — 配置文件解析或校验错误"""

    def __init__(
        self,
        message: str,
        code: str = "PROFILE_LOAD_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class ComplianceError(HarnessError):
    """合规扫描失败 — 规则检查未通过或扫描引擎异常"""

    def __init__(
        self,
        message: str,
        code: str = "COMPLIANCE_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class BridgeDeployError(HarnessError):
    """Bridge 部署失败 — 向 Agent 平台部署 hooks 配置时出错"""

    def __init__(
        self,
        message: str,
        code: str = "BRIDGE_DEPLOY_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)


class DowngradeError(HarnessError):
    """降级策略失败 — 自动降级引擎执行异常"""

    def __init__(
        self,
        message: str,
        code: str = "DOWNGRADE_FAILED",
        context: dict = None,
        detail: str = None,
    ):
        super().__init__(message=message, code=code, context=context, detail=detail)
