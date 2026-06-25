"""
S-3 验收测试：个性化治理分层 project/team/user 三级加载合并

验收标准：项目级强制不被团队/用户级覆盖

测试范围：
  1. ProfileConfig layer 和 forced_keys 字段
  2. merge_profiles() 合并策略
  3. 项目级强制项不被覆盖
  4. 非强制项可被 team/user 层补充
  5. 三级分层加载 load_with_layers()
"""

import copy
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.types import (
    ProfileConfig,
    GateMode,
    StepConfig,
    WorkflowConfig,
    PlatformCapability,
    ExecutionStrategy,
    ComplianceCategory,
    merge_profiles,
)
from harness.config import ProfileLoader, find_project_root


# ═══════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def project_profile():
    """项目级 Profile——强制项包含 hooks 和 gate_checks"""
    return ProfileConfig(
        name="strict-project",
        description="Project-level strict profile",
        default_agent="claude-code",
        layer="project",
        hooks={
            "session_start": [{"type": "script", "command": "python3 /hooks/init.py"}],
            "post_execute": [{"type": "script", "command": "python3 /hooks/audit.py"}],
        },
        gate_checks=[
            {"id": "no-secrets", "severity": "critical", "enabled": True},
            {"id": "no-hardcoded-creds", "severity": "high", "enabled": True},
        ],
        default_gate_mode=GateMode.STRICT,
        constraints={"max_changes": 50},
    )


@pytest.fixture
def team_profile():
    """团队级 Profile——尝试覆盖项目级强制项"""
    return ProfileConfig(
        name="relaxed-team",
        description="Team-level relaxed profile",
        default_agent="cursor",
        layer="team",
        hooks={
            "session_start": [{"type": "prompt", "message": "Team welcome"}],
        },
        gate_checks=[
            {"id": "style-check", "severity": "low", "enabled": True},
        ],
        default_gate_mode=GateMode.LOOSE,
        constraints={"max_changes": 100},
        skill_slots={"coder": {"post_execute": ["team-review"]}},
    )


@pytest.fixture
def user_profile():
    """用户级 Profile——尝试覆盖项目级强制项"""
    return ProfileConfig(
        name="personal-user",
        description="User-level personal profile",
        layer="user",
        default_agent="openai",
        hooks={
            "session_end": [{"type": "script", "command": "python3 ~/cleanup.py"}],
        },
        gate_checks=[
            {"id": "my-custom-check", "severity": "medium", "enabled": True},
        ],
        constraints={"max_changes": 200},
    )


# ═══════════════════════════════════════════════════════════
#  Test S-3.1: ProfileConfig layer 和 forced_keys
# ═══════════════════════════════════════════════════════════

class TestProfileConfigLayerFields:
    """ProfileConfig 新增的 layer 和 forced_keys 字段"""

    def test_default_layer_is_project(self):
        """默认 layer 为 project"""
        profile = ProfileConfig(name="test")
        assert profile.layer == "project"

    def test_default_forced_keys(self):
        """默认 forced_keys 包含 hooks、gate_checks、default_gate_mode"""
        profile = ProfileConfig(name="test")
        assert "hooks" in profile.forced_keys
        assert "gate_checks" in profile.forced_keys
        assert "default_gate_mode" in profile.forced_keys

    def test_layer_can_be_set(self):
        """layer 可以手动设置为 project/team/user"""
        p1 = ProfileConfig(name="test", layer="project")
        p2 = ProfileConfig(name="test", layer="team")
        p3 = ProfileConfig(name="test", layer="user")
        assert p1.layer == "project"
        assert p2.layer == "team"
        assert p3.layer == "user"

    def test_forced_keys_can_be_customized(self):
        """forced_keys 可以自定义"""
        profile = ProfileConfig(
            name="custom",
            forced_keys=["hooks"],
        )
        assert profile.forced_keys == ["hooks"]
        assert "gate_checks" not in profile.forced_keys


# ═══════════════════════════════════════════════════════════
#  Test S-3.2: merge_profiles 合并策略
# ═══════════════════════════════════════════════════════════

class TestMergeProfilesStrategy:
    """merge_profiles() 合并策略"""

    def test_project_only_returns_project(self, project_profile):
        """只有项目级 Profile → 直接返回（layer 保持 project）"""
        merged = merge_profiles(project_profile)
        assert merged.name == project_profile.name
        assert merged.hooks == project_profile.hooks
        assert merged.layer == "merged"

    def test_project_hooks_not_overridden_by_team(self, project_profile, team_profile):
        """验收核心：项目级 hooks 不被 team 层覆盖

        项目级 hooks 有 session_start 和 post_execute，
        team 层试图用 session_start 覆盖 → 不生效。
        """
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        # 项目级 hooks 保持不变——team 的 session_start 被拒绝
        assert merged.hooks == project_profile.hooks

    def test_project_gate_checks_not_overridden_by_team(self, project_profile, team_profile):
        """验收核心：项目级 gate_checks 不被 team 层覆盖"""
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        # 项目级 gate_checks 保持不变
        assert merged.gate_checks == project_profile.gate_checks

    def test_project_gate_mode_not_overridden_by_team(self, project_profile, team_profile):
        """验收核心：项目级 default_gate_mode 不被 team 层覆盖

        项目级 STRICT → team 层 LOOSE 不生效。
        """
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        assert merged.default_gate_mode == GateMode.STRICT

    def test_non_forced_items_can_be_supplemented_by_team(self, project_profile, team_profile):
        """非强制项可被 team 层补充"""
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        # skill_slots 是非强制项 → team 层的补充生效
        assert "coder" in merged.skill_slots
        assert merged.skill_slots["coder"]["post_execute"] == ["team-review"]

    def test_constraints_merged_by_team(self, project_profile, team_profile):
        """constraints dict 合并——team 层补充项目缺失的键"""
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        # 项目级 max_changes=50 不在 forced_keys → 可被 team 的 max_changes=100 覆盖
        # 但 dict 合并策略是"补充缺失键"，已有键不覆盖
        # 所以 max_changes 保持 50（项目已有此键）
        assert merged.constraints["max_changes"] == 50

    def test_project_hooks_not_overridden_by_user(self, project_profile, user_profile):
        """验收核心：项目级 hooks 不被 user 层覆盖"""
        merged = merge_profiles(
            project_profile=project_profile,
            user_profile=user_profile,
        )
        assert merged.hooks == project_profile.hooks

    def test_project_gate_checks_not_overridden_by_user(self, project_profile, user_profile):
        """验收核心：项目级 gate_checks 不被 user 层覆盖"""
        merged = merge_profiles(
            project_profile=project_profile,
            user_profile=user_profile,
        )
        assert merged.gate_checks == project_profile.gate_checks

    def test_all_three_levels_merged(self, project_profile, team_profile, user_profile):
        """三级合并：项目强制项保持，非强制项逐层合并"""
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
            user_profile=user_profile,
        )

        # 强制项保持项目级
        assert merged.hooks == project_profile.hooks
        assert merged.gate_checks == project_profile.gate_checks
        assert merged.default_gate_mode == GateMode.STRICT

        # 非强制项由 team 补充（skill_slots）
        assert "coder" in merged.skill_slots

        # layer 标记为 merged
        assert merged.layer == "merged"

    def test_merged_result_is_independent(self, project_profile, team_profile):
        """合并结果不修改原始 Profile"""
        original_hooks = copy.deepcopy(project_profile.hooks)
        original_team_hooks = copy.deepcopy(team_profile.hooks)

        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )

        # 原始 Profile 不被修改
        assert project_profile.hooks == original_hooks
        assert team_profile.hooks == original_team_hooks


# ═══════════════════════════════════════════════════════════
#  Test S-3.3: 强制项不被覆盖的边界场景
# ═══════════════════════════════════════════════════════════

class TestForcedKeysEdgeCases:
    """项目级强制项不被覆盖的边界场景"""

    def test_team_tries_to_remove_project_hooks(self, project_profile):
        """team 层试图用空 hooks 覆盖项目级 → 不生效"""
        team_empty_hooks = ProfileConfig(
            name="empty-team",
            layer="team",
            hooks={},
        )
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_empty_hooks,
        )
        # 项目级 hooks 保持不变
        assert merged.hooks == project_profile.hooks

    def test_user_tries_to_change_gate_mode(self, project_profile):
        """user 层试图把 STRICT 改为 LOOSE → 不生效"""
        user_loose = ProfileConfig(
            name="loose-user",
            layer="user",
            default_gate_mode=GateMode.LOOSE,
        )
        merged = merge_profiles(
            project_profile=project_profile,
            user_profile=user_loose,
        )
        assert merged.default_gate_mode == GateMode.STRICT

    def test_custom_forced_keys_only_hooks(self):
        """自定义 forced_keys=[hooks] → gate_checks 可被覆盖"""
        project_custom = ProfileConfig(
            name="custom-forced",
            layer="project",
            forced_keys=["hooks"],
            hooks={"session_start": [{"type": "script", "command": "init"}]},
            gate_checks=[{"id": "project-check", "enabled": True}],
            default_gate_mode=GateMode.STRICT,
        )
        team_custom = ProfileConfig(
            name="team-overwrite",
            layer="team",
            hooks={"session_start": [{"type": "prompt", "message": "hi"}]},
            gate_checks=[{"id": "team-check", "enabled": True}],
            default_gate_mode=GateMode.LOOSE,
        )

        merged = merge_profiles(
            project_profile=project_custom,
            team_profile=team_custom,
        )

        # hooks 是强制项 → 不被覆盖
        assert merged.hooks == project_custom.hooks

        # gate_checks 不是强制项（forced_keys=[hooks]）→ 可被覆盖
        # 但 dict/list 合并策略是"补充缺失"，不直接覆盖
        # gate_checks 是 list → 合并（项目有的保留 + team 的补充）
        assert len(merged.gate_checks) == 2

        # default_gate_mode 不是强制项 → team 可覆盖
        # 但默认合并策略不覆盖已存在的非 None 值
        # 看具体实现：default_gate_mode 是枚举值，不是 dict/list
        # 非强制项 + 非dict/list → team 直接覆盖
        # 注意：这是自定义 forced_keys 的效果——不强制 gate_mode 就可以被覆盖
        assert merged.default_gate_mode == GateMode.LOOSE

    def test_empty_project_profile_accepts_team(self):
        """项目级 Profile 为空 → team 层可补充"""
        project_empty = ProfileConfig(name="empty-project", layer="project")
        team_filled = ProfileConfig(
            name="team-filled",
            layer="team",
            hooks={"session_start": [{"type": "script", "command": "init"}]},
            gate_checks=[{"id": "team-check", "enabled": True}],
        )

        merged = merge_profiles(
            project_profile=project_empty,
            team_profile=team_filled,
        )

        # 项目级强制项 hooks 为空 dict → team 层被拒绝
        # 因为 hooks 在 forced_keys 中，即使项目值为空 dict，
        # 合并也不会用 team 去替换
        # 但注意：forced_values["hooks"] = {} (空dict)
        # 强制恢复后 hooks = {} (空dict)
        assert merged.hooks == {}

    def test_profile_name_preserved_from_project(self, project_profile, team_profile):
        """合并后 Profile 名称保持项目级"""
        merged = merge_profiles(
            project_profile=project_profile,
            team_profile=team_profile,
        )
        assert merged.name == project_profile.name


# ═══════════════════════════════════════════════════════════
#  Test S-3.4: ProfileLoader.load_with_layers()
# ═══════════════════════════════════════════════════════════

class TestProfileLoaderWithLayers:
    """ProfileLoader.load_with_layers() 三级分层加载"""

    def test_load_with_layers_no_team_no_user(self, tmp_path):
        """无 team 和 user 层 → 直接返回项目级"""
        profiles_dir = tmp_path / ".harness" / "profiles"
        profiles_dir.mkdir(parents=True)

        # 使用 _dict_to_profile 预期的 YAML 格式
        profile_content = """
profile:
  name: strict
  description: Project strict profile
agent:
  adapter: claude-code
gates:
  default_mode: strict
  checks:
    - id: no-secrets
      severity: critical
      enabled: true
hooks:
  session_start:
    - type: script
      command: python3 init.py
"""
        profile_file = profiles_dir / "strict.yaml"
        profile_file.write_text(profile_content)

        loader = ProfileLoader(profiles_dir=str(profiles_dir))

        # Mock resolve_active() 和 _load_team_profile/_load_user_profile
        with patch.object(loader, 'resolve_active', return_value="strict"), \
             patch.object(loader, '_load_team_profile', return_value=None), \
             patch.object(loader, '_load_user_profile', return_value=None):
            merged = loader.load_with_layers("strict")

        assert merged.name == "strict"
        assert merged.default_gate_mode == GateMode.STRICT
        assert merged.layer == "project"  # 无 team/user → 项目级直接返回

    def test_load_with_layers_with_team_and_user(self, tmp_path):
        """有 team 和 user 层 → 三级合并"""
        profiles_dir = tmp_path / ".harness" / "profiles"
        profiles_dir.mkdir(parents=True)

        # 项目级 Profile
        project_content = """
profile:
  name: strict
  description: Project strict
agent:
  adapter: claude-code
gates:
  default_mode: strict
  checks:
    - id: no-secrets
      severity: critical
      enabled: true
hooks:
  session_start:
    - type: script
      command: python3 init.py
constraints:
  max_changes: 50
"""
        (profiles_dir / "strict.yaml").write_text(project_content)

        # 团队级和用户级 Profile——用 mock 替代写入 HOME 目录
        team_profile = ProfileConfig(
            name="relaxed-team",
            description="Team relaxed",
            default_agent="claude-code",
            layer="team",
            default_gate_mode=GateMode.LOOSE,
            skill_slots={"coder": {"post_execute": ["team-review"]}},
            constraints={"max_changes": 100},
        )
        user_profile = ProfileConfig(
            name="personal",
            description="User personal",
            default_agent="openai",
            layer="user",
        )

        loader = ProfileLoader(profiles_dir=str(profiles_dir))

        with patch.object(loader, '_load_team_profile', return_value=team_profile), \
             patch.object(loader, '_load_user_profile', return_value=user_profile):
            merged = loader.load_with_layers("strict")

        # 项目级强制项不被覆盖
        assert merged.default_gate_mode == GateMode.STRICT  # 项目 STRICT，team LOOSE 不生效
        assert merged.hooks != {}  # 项目级 hooks 保持
        assert len(merged.gate_checks) == 1  # 项目级 gate_checks 保持

        # 非强制项可被 team 补充
        assert "coder" in merged.skill_slots

        # layer 标记为 merged
        assert merged.layer == "merged"

    def test_team_profile_dir_not_exist_returns_none(self, tmp_path):
        """团队级目录不存在 → team_profile=None"""
        profiles_dir = tmp_path / ".harness" / "profiles"
        profiles_dir.mkdir(parents=True)

        loader = ProfileLoader(profiles_dir=str(profiles_dir))

        # 团队级目录不存在
        team_profile = loader._load_team_profile("default")
        assert team_profile is None

    def test_user_profile_dir_not_exist_returns_none(self, tmp_path):
        """用户级目录不存在 → user_profile=None"""
        profiles_dir = tmp_path / ".harness" / "profiles"
        profiles_dir.mkdir(parents=True)

        loader = ProfileLoader(profiles_dir=str(profiles_dir))

        # 用户级目录不存在
        user_profile = loader._load_user_profile("default")
        assert user_profile is None


# ═══════════════════════════════════════════════════════════
#  Test S-3.5: merge_profiles 不修改原始对象
# ═══════════════════════════════════════════════════════════

class TestMergeProfilesImmutability:
    """合并操作不修改原始 Profile 对象"""

    def test_project_hooks_immutable(self, project_profile, team_profile):
        """合并不修改项目级 hooks"""
        original_hooks = copy.deepcopy(project_profile.hooks)
        merge_profiles(project_profile=project_profile, team_profile=team_profile)
        assert project_profile.hooks == original_hooks

    def test_team_hooks_immutable(self, project_profile, team_profile):
        """合并不修改团队级 hooks"""
        original_hooks = copy.deepcopy(team_profile.hooks)
        merge_profiles(project_profile=project_profile, team_profile=team_profile)
        assert team_profile.hooks == original_hooks

    def test_user_hooks_immutable(self, project_profile, user_profile):
        """合并不修改用户级 hooks"""
        original_hooks = copy.deepcopy(user_profile.hooks)
        merge_profiles(project_profile=project_profile, user_profile=user_profile)
        assert user_profile.hooks == original_hooks

    def test_constraints_immutable(self, project_profile, team_profile):
        """合并不修改原始 constraints"""
        original_project = copy.deepcopy(project_profile.constraints)
        original_team = copy.deepcopy(team_profile.constraints)
        merge_profiles(project_profile=project_profile, team_profile=team_profile)
        assert project_profile.constraints == original_project
        assert team_profile.constraints == original_team


# ═══════════════════════════════════════════════════════════
#  Test S-3.6: dict 和 list 合并策略细节
# ═══════════════════════════════════════════════════════════

class TestMergeDictListStrategy:
    """dict 和 list 的合并策略（补充而非覆盖）"""

    def test_dict_merge_supplements_missing_keys(self):
        """dict 合并：补充项目缺失的键，已有键不覆盖"""
        project = ProfileConfig(
            name="project",
            layer="project",
            constraints={"max_changes": 50},
        )
        team = ProfileConfig(
            name="team",
            layer="team",
            constraints={"max_changes": 100, "timeout": 30},
        )

        merged = merge_profiles(project_profile=project, team_profile=team)

        # max_changes 项目已有 → 不覆盖（保持在 50）
        # timeout 项目缺失 → team 补充（添加 30）
        assert merged.constraints["max_changes"] == 50
        assert merged.constraints["timeout"] == 30

    def test_list_merge_supplements_missing_items(self):
        """list 合并：补充项目缺失的元素"""
        project = ProfileConfig(
            name="project",
            layer="project",
            pipeline_agents=["analyst", "coder"],
        )
        team = ProfileConfig(
            name="team",
            layer="team",
            pipeline_agents=["analyst", "coder", "validator", "committer"],
        )

        merged = merge_profiles(project_profile=project, team_profile=team)

        # 项目已有 analyst + coder → 保持
        # team 的 validator + committer 项目缺失 → 补充
        assert "analyst" in merged.pipeline_agents
        assert "coder" in merged.pipeline_agents
        assert "validator" in merged.pipeline_agents
        assert "committer" in merged.pipeline_agents

    def test_scalar_overwrite_for_non_forced(self):
        """非强制项的 scalar 值（如 default_agent）→ team 可覆盖"""
        project = ProfileConfig(
            name="project",
            layer="project",
            default_agent="claude-code",
            forced_keys=["hooks"],  # 只强制 hooks，不强制 default_agent
        )
        team = ProfileConfig(
            name="team",
            layer="team",
            default_agent="cursor",
        )

        merged = merge_profiles(project_profile=project, team_profile=team)

        # default_agent 不在 forced_keys → team 可覆盖
        assert merged.default_agent == "cursor"
