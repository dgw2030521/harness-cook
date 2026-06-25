"""
harness-cook 日志配置

统一日志格式 + CLI 参数控制 + stderr 分离
"""

import logging
import sys
import json
from typing import Optional


class HarnessFormatter(logging.Formatter):
    """harness-cook 统一日志格式"""

    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        if self.json_mode:
            return json.dumps({
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "module": record.module,
                "message": record.getMessage(),
            }, ensure_ascii=False)
        else:
            return f"[{record.levelname}] {record.module}: {record.getMessage()}"


def configure_logging(
    level: str = "INFO",
    json_mode: bool = False,
    quiet: bool = False,
) -> None:
    """配置 harness-cook 全局日志

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        json_mode: JSON 结构化输出
        quiet: 只输出 ERROR及以上
    """
    if quiet:
        level = "ERROR"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(HarnessFormatter(json_mode=json_mode))

    # 配置 harness logger
    harness_logger = logging.getLogger("harness")
    harness_logger.setLevel(getattr(logging, level.upper()))
    harness_logger.handlers.clear()
    harness_logger.addHandler(handler)

    # 防止传播到 root logger
    harness_logger.propagate = False