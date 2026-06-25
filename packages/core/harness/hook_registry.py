"""
Hook 点映射注册表

统一管理所有 Agent 平台的 hook 点映射，提供：
  - 注册：各适配器在模块加载时注册自己的映射表
  - 覆盖度报告：全局视图，每个槽位在各平台的映射情况
  - 验证：确保注册的槽位名是合法的 SkillSlotName 值

设计原则：
  - 映射表仍然属于各适配器（不同平台事件名和语义各不相同）
  - 注册表是观察层，用于验证和报告，不替代适配器自己的 translate_hooks 逻辑
  - 适配器 translate_hooks() 直接引用自己的映射表常量，不通过注册表查找
"""

import logging
from typing import Dict, Set

from harness.types import SkillSlotName

logger = logging.getLogger("harness.hook_registry")


class HookPointRegistry:
    """统一管理所有平台的 hook 点映射

    用法：
        # 适配器模块加载时注册
        HookPointRegistry.register("claude-code", HOOK_POINT_MAP)

        # 查看覆盖度
        report = HookPointRegistry.coverage_report()
        for adapter, info in report.items():
            print(f"{adapter}: covered={info['covered']}, uncovered={info['uncovered']}")

        # 验证所有注册映射的合法性
        HookPointRegistry.validate_all()
    """

    _mappings: Dict[str, Dict[str, str]] = {}

    @classmethod
    def register(cls, adapter_name: str, mapping: Dict[str, str]) -> None:
        """注册适配器的 hook 点映射表

        Args:
            adapter_name: 适配器标识（如 "claude-code", "hermes"）
            mapping: 槽位名 → 平台事件名的映射字典

        Raises:
            ValueError: 如果映射中有非法的槽位名（不属于 SkillSlotName）
        """
        # 验证所有槽位名是合法的 SkillSlotName 值
        valid_slots = set(SkillSlotName._value2member_map_.keys())
        invalid_keys = set(mapping.keys()) - valid_slots
        if invalid_keys:
            raise ValueError(
                f"Invalid slot names in {adapter_name} mapping: {invalid_keys}. "
                f"Valid slots: {valid_slots}"
            )

        cls._mappings[adapter_name] = mapping
        logger.info(f"Registered hook mapping for '{adapter_name}': {len(mapping)} slots")

    @classmethod
    def get_mapping(cls, adapter_name: str) -> Dict[str, str]:
        """获取指定适配器的映射表

        Args:
            adapter_name: 适配器标识

        Returns:
            映射字典，未注册的适配器返回空字典
        """
        return cls._mappings.get(adapter_name, {})

    @classmethod
    def coverage_report(cls) -> Dict[str, Dict[str, Set[str]]]:
        """生成全局覆盖度报告

        返回每个适配器覆盖了哪些槽位、未覆盖哪些槽位。

        Returns:
            {
                "claude-code": {
                    "covered": {"session_start", "pre_execute", ...},
                    "uncovered": {"on_gate_pass", "pre_commit", ...},
                },
                "hermes": { ... },
            }
        """
        all_slots = set(SkillSlotName._value2member_map_.keys())
        report = {}

        for adapter_name, mapping in cls._mappings.items():
            covered = set(mapping.keys())
            uncovered = all_slots - covered
            report[adapter_name] = {
                "covered": covered,
                "uncovered": uncovered,
                "coverage_pct": round(len(covered) / len(all_slots) * 100, 1) if all_slots else 0,
            }

        return report

    @classmethod
    def validate_all(cls) -> bool:
        """验证所有已注册映射的合法性

        Returns:
            True 如果所有映射都合法
        """
        valid_slots = set(SkillSlotName._value2member_map_.keys())
        all_ok = True

        for adapter_name, mapping in cls._mappings.items():
            invalid_keys = set(mapping.keys()) - valid_slots
            if invalid_keys:
                logger.error(
                    f"Invalid slot names in {adapter_name}: {invalid_keys}"
                )
                all_ok = False

        return all_ok

    @classmethod
    def all_registered_adapters(cls) -> Set[str]:
        """返回所有已注册映射的适配器名称"""
        return set(cls._mappings.keys())

    @classmethod
    def clear(cls) -> None:
        """清空所有注册（仅用于测试）"""
        cls._mappings.clear()
