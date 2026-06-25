# harness-cook — Agent Governance Integration Bus

[简体中文](README.md) | [English](README.en.md)

> **Hooks define constraints, Skills define steps, Agents define roles.**

harness-cook is an **Agent Governance Integration Bus** — providing declarative configuration, one-click deployment, and observable governance for AI Agents like Claude Code.

## Supported Agent Platforms

harness-cook uses the adapter pattern, with 5 adapters covering different strategy tiers:

| Adapter | Target Platform | Hooks? | Governance Strength | Yield Strategy | Prompt Strength | Deployment Strategy |
|---------|-----------------|--------|---------------------|----------------|-----------------|---------------------|
| `claude-code` | **Claude Code** ✅ | ✅ native hooks | **Mandatory** | COOPERATIVE | mild | hooks → settings.json auto-trigger |
| `copilot-cli` | **GitHub Copilot CLI** ✅ | ✅ has hook concept | **Mandatory** | COOPERATIVE | mild | hooks + MCP dual-channel |
| `hermes` | **Hermes** ✅ | ❌ no native hooks | Advisory → near-mandatory | FALLBACK | **mandatory** | Governance via MCP Server tools |
| `cursor` | **Cursor IDE** 🔶 | ❌ no hooks | Advisory → near-mandatory | FALLBACK | **mandatory** | MCP server + metadata only |
| `openai` | **OpenAI/Codex** 🔶 | ❌ no hooks | Advisory → near-mandatory | FALLBACK | **mandatory** | function calling definitions |

> ✅ = Governance auto-enforced 🔶 = Governance via mandatory prompt + MCP tools (Agent usually follows but theoretically bypassable)
> **Yield Strategy (S-5)**: ENHANCEMENT = the platform has complete native guardrails (redact + block), and harness yields to an optional enhancement; COOPERATIVE = the platform has partial capabilities (e.g. block), and harness supplements uncovered scenarios; FALLBACK = the platform has no equivalent capability, and harness takes full responsibility. All 5 current adapters have `supports_realtime_redact=False`, effectively falling into COOPERATIVE (claude-code/copilot-cli, with realtime_block) or FALLBACK (hermes/cursor/openai); the ENHANCEMENT branch is reserved for future evolution and will be activated when a platform with native real-time redaction appears.
> **Git Hook Fallback**: All Agents auto-install a git pre-commit hook; non-compliant code cannot pass commit (dual insurance).

**Specify the adapter in the Profile:**

```yaml
agent:
  adapter: claude-code  # options: claude-code | copilot-cli | hermes | cursor | openai
```

## Documentation

- **Online docs site**: see `playground/docs/` (VitePress source); preview locally with `pnpm dev:docs`
- **Design analysis docs**: see the [docs/](docs/) directory (numbered architecture & product analysis archives)
- **Changelog**: see [CHANGELOG.md](CHANGELOG.md)

## Design Goals

### The Problem

AI Agents (e.g. Claude Code) are powerful but lack structured governance:
- hooks/skills are scattered across manually-edited config files, with no unified management
- Different projects need different governance strategies, but there is no switchable Profile
- What the Agent executed and the outcome lack observability
- There is no standardized "install/uninstall" flow

### The Solution

harness-cook provides three things:

1. **Declarative configuration** — Define hooks/skills/gates via YAML files instead of hand-writing settings.json
2. **One-click deployment** — A single command translates the config into the Agent-native format and writes it
3. **Observable** — Every execution has an audit log; the visualization UI displays it in real time

### Core Concepts

<p align="center"><img src="docs/images/arch-profile-flow.png" alt="Profile → DAGEngine architecture diagram" width="548"></p>

<details>
<summary>ASCII version</summary>

```
┌─────────────────────────────────────────────────────────────┐
│  Profile Configuration                                      │
│  .harness/profiles/default.yaml                             │
│  (hooks + skills + gates all declared in one file)          │
└──────────────────────────────┬──────────────────────────────┘
                               │ load
┌──────────────────────────────▼──────────────────────────────┐
│  HarnessConfig                                              │
└───────┬──────────────────────────────┬──────────────────────┘
        │                              │
┌───────▼────────┐             ┌───────▼──────────────────────┐
│  SkillRegistry │             │  HarnessBridge               │
│  (register/    │             │  (AdapterRegistry +          │
│   lookup/      │             │   protocol translation)      │
│   slot/execute)│             │  Profile → Agent-native      │
└───────┬────────┘             └───────┬──────────────────────┘
        │                              │
        │                      ┌───────▼──────────┐
        │                      │  Claude Code     │
        │                      │  settings.json   │
        │                      │  (hooks section) │
        │                      └──────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────┐
│  DAGEngine                                                  │
│  _execute_node flow:                                        │
│    1. run_skill_slot(pre_execute)    ← Skills define steps  │
│    2. agent.execute(task)            ← Agents define roles  │
│    3. gate.check(artifacts)          ← Hooks define limits  │
│    4. run_skill_slot(post_execute)   ← Skills define steps  │
│    5. run_skill_slot(on_gate_fail)   ← Skills define steps  │
└─────────────────────────────────────────────────────────────┘
```

</details>

**Hooks define constraints** — Set constraints at each phase of Agent execution (gate checks, security scans, PII filtering).

**Skills define steps** — Pluggable capability units mounted onto 17 slot points (three tiers: 5 core + 2 extension + 10 theoretical).

**Agents define roles** — 5 adapters managed by AdapterRegistry (S-1 plugin mechanism: adding a new platform takes just one .py file).

---

## Quick Start

### Prerequisites

- Python 3.10+
- A supported Agent platform (Claude Code / Copilot CLI / Hermes enforce mandatory governance ✅; Cursor / Codex advisory governance 🔶)

### Installation

```bash
git clone https://github.com/harness-cook/harness-cook.git
cd harness-cook
./install.sh       # one-click install (registers the harness command)
harness activate   # one-click activation (configures MCP + hooks + skills)

# Deploy to a different Agent platform
harness activate --agent hermes    # Hermes
harness activate --agent cursor    # Cursor IDE
harness activate --agent copilot-cli  # Copilot CLI
```

Restart the Agent platform to take effect.

### Uninstall

```bash
harness deactivate
```

Fully restored, leaving no config residue.

### Custom Configuration

harness-cook ships with three tiered Profiles:

| Profile | Gate Mode | Pipeline Steps | Hooks | Use Case |
|---------|-----------|----------------|-------|----------|
| `basic` | LOOSE (only intercepts critical) | 3 steps (analyst→coder→committer) | 2 | Personal projects, fast iteration |
| `default` | HYBRID (allows low, intercepts medium+) | 5 steps | 3 | Team collaboration, routine dev |
| `enterprise` | STRICT (zero tolerance) | 5 steps (incl. reviewer+validator) | 9 | Production, strict compliance |

#### Profile Selection Priority

The system automatically decides which Profile to use — no manual intervention needed:

| Priority | Mechanism | Purpose | Example |
|----------|-----------|---------|---------|
| 1️⃣ Highest | `HARNESS_PROFILE` env var | CI/automation override | `HARNESS_PROFILE=enterprise` |
| 2️⃣ Mid | `.harness/env` file `HARNESS_PROFILE=` | Machine-level persistence (written by activate, gitignored) | — |
| 3️⃣ | `.harness/active_profile` marker file | Project-level persistent choice (committed to Git, team-shared) | File content `basic` |
| 4️⃣ Lowest | `"default"` fallback | Default when nothing is selected | — |

#### Adapter Selection Priority

The adapter (deployment target platform) selection also follows a priority chain, orthogonal to the Profile:

| Priority | Mechanism | Purpose | Example |
|----------|-----------|---------|---------|
| 1️⃣ Highest | `--agent` CLI arg | Explicit user override | `harness activate --agent hermes` |
| 2️⃣ | `HARNESS_ADAPTER` env var | CI/automation override | `HARNESS_ADAPTER=cursor` |
| 3️⃣ | `.harness/env` file `HARNESS_ADAPTER=` | Machine-level persistence (written by activate, gitignored) | — |
| 4️⃣ | `.harness/active_adapter` marker file | Project-level persistent choice (committed to Git, team-shared) | File content `hermes` |
| 5️⃣ | Profile `agent.adapter` field | Config declaration — serves as fallback default | — |
| 6️⃣ Lowest | `"claude-code"` fallback | Default when nothing is configured | — |

> **Adapter and Profile are orthogonal**: Adapter decides "where to deploy" (runtime/environment decision); Profile decides "what rules to deploy" (governance decision).

```bash
# Via environment variable (CI / one-off override)
export HARNESS_PROFILE=enterprise

# Via marker file (persistent, team-shared)
# Write to the .harness/active_profile file
echo "basic" > .harness/active_profile
```

```python
# Python API
from harness.config import switch_profile, load_profile

switch_profile("enterprise")  # writes marker file → team-shared
profile = load_profile()      # auto-resolve → enterprise
profile = load_profile("basic")  # explicit → basic (ignores resolve)
```

#### Custom YAML

Edit `.harness/profiles/default.yaml` or create a new Profile:

```yaml
profile:
  name: default
  description: My project configuration

agent:
  adapter: claude-code

pipeline:
  agents: [analyst, coder, reviewer, validator, committer]
  steps:
    - name: analyze-requirement
      skill: requirement-analysis
    - name: implement-code
      skill: code-generation
    - name: review-code
      skill: auto-review

hooks:
  session_start:
    - type: script
      command: "python3 packages/hooks/hook-session-init.py"
  post_execute:
    - type: skill
      skill_id: auto-audit

gates:
  default_mode: hybrid
  checks:
    - id: no-secrets
      enabled: true
    - id: no-eval
      enabled: true
```

### CLI Commands

```bash
harness activate              # one-click activation (default Claude Code)
harness activate --agent hermes  # deploy to Hermes
harness activate --agent cursor  # deploy to Cursor IDE
harness deactivate            # one-click uninstall
harness log                   # view execution logs
harness log --type skill      # filter by type
harness log --follow          # follow in real time
harness dashboard             # launch the visualization dashboard (auto-detects current project)
harness dashboard --port 9000 # specify a port
harness check .               # compliance scan
harness audit                 # view audit records
harness version               # version number
```

**Dashboard project auto-detection priority:**

| Priority | Detection method | Description |
|----------|------------------|-------------|
| 1 | `HARNESS_PROJECT_DIR` env var | Explicit CLI arg, highest priority |
| 2 | `CLAUDE_PROJECT_DIR` env var | Auto-set in the Claude Code scenario |
| 3 | Walk up from CWD looking for `.harness/` | **Core logic**: the first parent containing a `.harness` directory is recognized as the project; the search stops at the home directory (does not match the `~/.harness` global config) |
| 4 | `git rev-parse --show-toplevel` | Falls back to the git root when no `.harness` is found |
| 5 | Current working directory | Neither `.harness` nor a git repo |

> 💡 Run `harness dashboard` inside a project directory and it launches that project's dashboard by default. Whether or not the project has run `harness activate`, as long as the `.harness/` directory exists it is recognized.

---

## Architecture Design

### Layered Architecture

<p align="center"><img src="docs/images/arch-layers.png" alt="Layered architecture diagram" width="541"></p>

<details>
<summary>ASCII version</summary>

```
┌─────────────────────────────────────────────────────────────┐
│  User Layer                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │  CLI     │  │  MCP     │  │ Dashboard│  │  SDK     │     │
│  │  cmds    │  │  Server  │  │ Web UI   │  │ Python/TS│     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
└───────┼──────────────┼──────────────┼──────────────┼────────┘
        │              │              │              │
┌───────▼──────────────▼──────────────▼──────────────▼────────┐
│  Core Layer                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Profile  │  │ Skill    │  │ Bridge   │  │ Audit    │     │
│  │ Config   │  │ Registry │  │ Deploy   │  │ Logger   │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       │              │              │              │        │
│  ┌────▼──────────────▼──────────────▼──────────────▼────┐   │
│  │                 DAGEngine                            │   │
│  │  (topo sort + parallel sched + gate checks + slots)  │   │
│  └────┬──────────────┬──────────────┬──────────────┬────┘   │
│       │              │              │              │        │
│  ┌────▼─────┐  ┌─────▼────┐  ┌─────▼────┐  ┌─────▼─────┐    │
│  │ Agent    │  │ Gate     │  │Compliance│  │ EventBus  │    │
│  │ Registry │  │ Engine   │  │ Engine   │  │           │    │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘    │
└─────────────────────────────────────────────────────────────┘
```

</details>

### Core Modules

| Module | Responsibility | Key classes |
|--------|----------------|-------------|
| `types.py` | Type definitions | SkillSlotName (three-tier), ExecutionStrategy, PlatformCapability, merge_profiles, ProfileConfig |
| `config.py` | Config system + three-tier merge | HarnessConfig, ProfileLoader, load_with_layers |
| `skill_registry.py` | Skill registry | SkillRegistry, SkillRecord |
| `bridge.py` | Protocol translation + adapter registry | HarnessBridge, AdapterRegistry (S-1) |
| `audit_logger.py` | Audit logging | write_audit_log, log_skill_execute |
| `engine.py` | DAG orchestration | DAGEngine, _run_skill_slot |
| `gates.py` | Quality gates | GateEngine, GateCheck |
| `compliance.py` | Compliance engine unified entry (re-export) | ComplianceEngine, 6 rule packs |
| `registry.py` | Agent registry | AgentRegistry |
| `bus.py` | Event bus | EventBus |
| `pattern_registry.py` | Trigger pattern matching (E-5) | PatternRegistry, PatternDefinition |
| `governance_semantics.py` | Governance semantic standardization (S-2) | GovernanceSemanticRegistry, GovernanceSemantic |
| `gate_notification.py` | Gate approval + downgrade notification | GateManager, AutoDowngrade, GateApprovalRecord |
| `knowledge.py` | Knowledge management + rule activation (S-4) | LocalKnowledgeProvider, InsightActivationStore |
| `downgrade.py` | Standalone downgrade engine | DowngradeEngine, DowngradePolicy |

### Skill Slot Points

**17 slot points, three tiers (E-8 refactor):**

| Tier | Count | Slots | Description |
|------|-------|-------|-------------|
| **Core channel** | 6 | SESSION_START, POST_EXECUTE, ON_ERROR, ON_GATE_PASS, ON_GATE_FAIL, ON_ESCALATION | Invoked by DAGEngine integration; the first 5 are wired to hooks by default in Profile YAML, ON_ESCALATION is triggered by the gate escalation path (engine.py integration) and requires a registered Skill to consume it |
| **Extension channel** | 2 | SESSION_END, PRE_EXECUTE | Backed by real hook scripts; optionally shown in Profile YAML |
| **Theoretical channel** | 9 | PRE_TOOL_USE, POST_TOOL_USE, ON_FILE_CHANGE, PRE_COMMIT, POST_COMMIT, ON_DELEGATE, ON_CONFLICT, ON_DECISION, USER_PROMPT_SUBMIT | Enum definitions only, no production integration yet |

See `docs/45-Slot分层映射表-20260616.md` for the detailed mapping.

---

## Core Implementation

### 1. Profile Configuration System

**File:** `packages/core/harness/config.py`

```python
@dataclass
class HarnessConfig:
    # Legacy config
    project_name: str
    log_level: str
    default_gate_mode: GateMode

    # Scaffold config (new)
    active_profile: str              # active Profile
    hooks: dict                      # declarative Hook config
    skill_slots: dict                # Skill slot config
```

**Profile loading and auto-selection:**

```python
from harness.config import load_profile, list_profiles, resolve_active_profile, switch_profile

# Auto-select: HARNESS_PROFILE env > .harness/active_profile > "default"
profile = load_profile()            # auto-resolve → active Profile
print(profile.hooks)                 # {"session_start": [...], ...}
print(profile.pipeline_agents)       # ["analyst", "coder", ...]

# Switch Profile (writes marker file, persistent)
switch_profile("enterprise")

# Explicit (ignores auto-selection)
profile = load_profile("basic")

# List available Profiles
profiles = list_profiles()           # ["basic", "default", "enterprise"]
```

**Three-tier merge (S-3) — project-level forced, team/user-level override:**

```python
from harness.config import ProfileLoader
from harness.types import merge_profiles

loader = ProfileLoader()

# Load a Profile with layered merge (project → team → user, three tiers)
profile = loader.load_with_layers("enterprise")
# Project-level forced_keys (hooks, gate_checks, default_gate_mode) cannot be overridden by team/user
# Team/user can override description, pipeline_agents, workflow, etc.

# Call the merge function directly
merged = merge_profiles(project_profile, team_profile, user_profile)
# → returns the merged ProfileConfig; forced_keys guarantee project-level enforced items stay unchanged
```

### 2. Skill Registry

**File:** `packages/core/harness/skill_registry.py`

```python
from harness.skill_registry import get_skill_registry, register_builtin_skills
from harness.types import SkillDefinition, SkillSlotName

registry = get_skill_registry()

# Register a Skill
registry.register(SkillDefinition(
    id="my-skill",
    name="Custom check",
    slot=SkillSlotName.POST_EXECUTE,
    entry_point="skills/my-skill/run.py",
    tags=["custom"],
))

# Find by slot
skills = registry.find_by_slot(SkillSlotName.POST_EXECUTE)

# Execute a Skill
result = registry.execute_skill("my-skill", context={"task_id": "t-1"})
```

**DAGEngine integration:**
```python
# engine.py _execute_node method
def _execute_node(self, node, ctx, global_context):
    self._run_skill_slot(node.id, SkillSlotName.PRE_EXECUTE, ctx, global_context)
    # ... agent.execute(task) ...
    self._run_skill_slot(node.id, SkillSlotName.POST_EXECUTE, ctx, global_context)
```

### 3. Bridge Deploy

**File:** `packages/core/harness/bridge.py`

```python
from harness.bridge import HarnessBridge
from harness.config import load_profile

bridge = HarnessBridge()
profile = load_profile("default")

# Deploy — select adapter via AdapterRegistry, branch governance strategy by capability
result = bridge.deploy(profile)
# → AdapterRegistry three-tier discovery: built-in → .harness/adapters/ → internal scan
# → hook-capable Agent (COOPERATIVE): mild prompt + hooks auto-trigger
# → no-hooks Agent (FALLBACK): mandatory prompt + git hook fallback
# → writes config + records audit log
```

**Translation rules:**

| Profile hooks | → | Claude Code |
|---------------|---|-------------|
| `session_start` | → | `SessionStart` |
| `pre_execute` | → | `PreToolUse` |
| `post_execute` | → | `PostToolUse` |
| `session_end` | → | `Stop` |

**Conditional branching strategy (incl. S-5 yield detection):**

| Adapter | `supports_hooks` | Yield strategy | Prompt strength | Git hook |
|---------|------------------|----------------|-----------------|----------|
| Claude/Copilot | `True` | COOPERATIVE | mild (light hint) | ✅ fallback |
| Hermes | `False` | FALLBACK | mandatory (strong hint, auto-upgrade) | ✅ fallback |
| Cursor/OpenAI | `False` | FALLBACK | mandatory (strong hint, auto-upgrade) | ✅ fallback |

> The FALLBACK strategy auto-upgrades prompt_strength from mild to mandatory — this is the core of yield detection: when there is no hook capability, a strong prompt must compensate.

### 4. Observability

**Audit log:** Every Skill execution and Bridge deploy is auto-written to `.harness/audit/`

```json
{
  "timestamp": "2026-06-12T11:05:23.456789",
  "event": "skill_execute",
  "skill_id": "auto-audit",
  "status": "completed",
  "duration_ms": 125
}
```

**CLI view:**
```bash
harness log --type skill --limit 10
```

**Dashboard visualization:**
```bash
harness dashboard    # http://localhost:8765
```

### 5. Adapter Plugin Mechanism (S-1)

**Adding a new platform takes just one .py file:**

```python
# .harness/adapters/my_platform.py
from harness.adapters.base import IAgentAdapter

class MyPlatformAdapter(IAgentAdapter):
    platform_id = "my-platform"
    supports_hooks = False

    def translate_hooks(self, hooks: dict) -> dict:
        return {}  # no hook support

    def translate_profile(self, profile) -> dict:
        return {"instructions": self._build_instructions(profile)}
```

**Three-tier discovery order:** built-in adapters → `.harness/adapters/` directory → `harness.adapters` internal scan

### 6. Governance Semantic Standardization (S-2)

**Unify the semantic description of governance actions; translation is consistent across adapters:**

```python
from harness.governance_semantics import get_governance_semantic_registry

registry = get_governance_semantic_registry()

# Query a semantic definition
semantic = registry.get("pii_filter")
# → GovernanceSemantic(id="pii_filter", actions=[BLOCK, WARN],
#     description="PII content filter", patterns=[ID number, phone, bank card])

# Cross-adapter translation
result = registry.translate_governance("pii_filter", adapter="hermes")
# → The Hermes adapter translates pii_filter into a function_calling definition
```

### 7. Knowledge Base Rule Activation (S-4)

**Activate an Insight into a compliance rule with one click, and roll back with one click:**

```python
from harness.knowledge import get_knowledge_provider

provider = get_knowledge_provider()

# Query the knowledge base
results = provider.query("no-hardcoded-secrets")

# One-click activate an Insight as a compliance rule
activation = provider.activate("insight-no-secrets")
# → Insight → ComplianceRule, auto-written into a rule pack

# One-click roll back
provider.deactivate("insight-no-secrets")
# → rule removed; the Insight returns to the inactive state
```

### 8. Yield Detection Mechanism (S-5)

**Automatically select a governance strategy based on adapter capabilities:**

```python
from harness.types import PlatformCapability, ExecutionStrategy

cap = PlatformCapability(
    adapter_id="hermes",
    supports_realtime_redact=False,
    supports_realtime_block=False,
    supports_pii_detection=False,
    supports_compliance_scan=False,
)

strategy = cap.resolve_execution_strategy()
# → ExecutionStrategy.FALLBACK  (no hooks, upgraded to mandatory prompt)

# Claude Code strategy (has realtime_block, no realtime_redact)
cap_cc = PlatformCapability(adapter_id="claude-code", supports_realtime_redact=False, supports_realtime_block=True, ...)
strategy = cap_cc.resolve_execution_strategy()
# → ExecutionStrategy.COOPERATIVE (partial capability, mild prompt + hooks auto-trigger)
```

---

## Observability Dashboard

Launch the Dashboard:

```bash
harness dashboard
# Open http://localhost:8765 in a browser
```

**10 tabs:**

| Tab | Content |
|-----|---------|
| Overview | Stat cards + Hook execution distribution + Gate pass rate |
| Audit | Audit record search (decision-chain / action-chain tracing) |
| Agent | Registered Agent list + recent activity |
| **Skills** | Registered Skills + execution stats (execution count / error count) |
| **Profile** | Current Profile config (hooks/gates details) |
| **Hooks** | Hook execution stats (by type / slot distribution) |
| Compliance | Compliance scan + rule pack list |
| Gates | Gate check history |
| Event stream | Real-time event stream |
| **Knowledge** | Knowledge base entries (browse by type / source) |

---

## MCP Server

harness-cook exposes 25 tools through the MCP Server:

| Tool | Function |
|------|----------|
| `harness_check` | Compliance scan |
| `harness_guardrails_check` | PII / safety guardrail check |
| `harness_rule_import` | Rule import (SonarQube/ArchUnit/DepCruiser) |
| `harness_audit` | Audit record query |
| `harness_trace_export` | OTel/Traceloop export |
| `harness_status` | Aggregated system status |
| `harness_plan` | DAG topology visualization |
| `harness_run` | DAG workflow execution |
| `harness_pipeline_run` | Coding pipeline execution |
| `harness_pipeline_status` | Pipeline status query |
| `harness_gate_create` | Create a gate |
| `harness_gate_approve` | Gate approval (E-9) |
| `harness_hook_trigger` | MCP trigger (E-5; after a hook fires, invokes guardrails for pattern matching) |
| `harness_register` | Register an Agent |
| `harness_agent_list` | List Agents |
| `harness_profile_list` | List Profiles |
| `harness_profile_load` | Load a Profile |
| `harness_skill_list` | List Skills |
| `harness_skill_register` | Register a Skill |
| `harness_bridge_deploy` | Deploy to an Agent platform (Claude/Copilot/Hermes/Cursor/Codex) |
| `harness_knowledge_query` | Knowledge base query |
| `harness_knowledge_search` | Knowledge base semantic search |
| `harness_knowledge_stats` | Knowledge base stats |
| `harness_knowledge_activate` | Insight → rule one-click activation (S-4) |
| `harness_knowledge_deactivate` | Rule one-click rollback (S-4) |

---

## Project Structure

```
harness-cook/
├── packages/
│   ├── core/                        Core framework (Python)
│   │   ├── harness/
│   │   │   ├── __init__.py          Unified exports
│   │   │   ├── types.py             Type definitions (SkillSlotName, ExecutionStrategy, merge_profiles, ...)
│   │   │   ├── config.py            Config system + ProfileLoader + three-tier merge (S-3)
│   │   │   ├── skill_registry.py    Skill registry + slot mechanism
│   │   │   ├── bridge.py            Bridge Deploy + AdapterRegistry (S-1)
│   │   │   ├── audit_logger.py      Audit log writer
│   │   │   ├── bus.py               Event bus
│   │   │   ├── registry.py          Agent registry
│   │   │   ├── engine.py            DAG orchestration engine (+ Skill slot execution)
│   │   │   ├── gates.py             Quality gates
│   │   │   ├── compliance.py        Compliance engine unified entry (re-export)
│   │   │   ├── guardrails.py        Input/output guardrails
│   │   │   ├── scheduler.py         Resource-aware scheduling
│   │   │   ├── negotiation.py       Multi-Agent negotiation
│   │   │   ├── audit.py             Audit storage
│   │   │   ├── learning.py          Self-learning (Insight → rule activation, S-4)
│   │   │   ├── knowledge.py         Knowledge management + InsightActivationStore (S-4)
│   │   │   ├── constraints.py       Constraint system
│   │   │   ├── decorators.py        @harness_agent decorator
│   │   │   ├── llm.py               Agent resource constraints (token budget / model tiering / tracking)
│   │   │   ├── rollback.py          Auto-rollback
│   │   │   ├── call_graph.py        Call-graph analysis
│   │   │   ├── taint.py             Taint tracking
│   │   │   ├── report.py            Visualization report
│   │   │   ├── logging_config.py    Logging config
│   │   │   ├── pattern_registry.py  Trigger pattern matching (E-5)
│   │   │   ├── governance_semantics.py Governance semantic standardization (S-2)
│   │   │   ├── gate_notification.py Gate approval + downgrade notification
│   │   │   ├── downgrade.py         Standalone downgrade engine
│   │   │   ├── adapters/            Adapter plugins (S-1)
│   │   │   │   ├── base.py          IAgentAdapter contract
│   │   │   │   ├── claude_code.py   Claude Code adapter
│   │   │   │   ├── copilot_cli.py   Copilot CLI adapter
│   │   │   │   ├── hermes.py        Hermes adapter
│   │   │   │   ├── cursor.py        Cursor adapter
│   │   │   │   └── openai.py        OpenAI/Codex adapter
│   │   │   └── rule_packs/          Built-in compliance rule packs
│   │   │       ├── coding.py        Coding compliance
│   │   │       ├── security.py      Security compliance
│   │   │       ├── data.py          Data compliance
│   │   │       ├── devops.py        DevOps compliance
│   │   │       ├── architecture.py  Architecture compliance
│   │   │       └── legal.py         Legal compliance (new)
│   │   ├── tests/                   Core tests (1644)
│   │   └── pyproject.toml
│   │
│   ├── cli/                         CLI tool
│   │   ├── harness_cli.py           Main entry (14 subcommands)
│   │   ├── cli_commands/
│   │   │   ├── activate.py          One-click activation (Profile → Bridge → settings.json)
│   │   │   ├── deactivate.py        One-click uninstall (fully restored)
│   │   │   ├── log.py               View execution logs
│   │   │   ├── dashboard.py         Launch Dashboard
│   │   │   ├── check.py             Compliance scan
│   │   │   ├── audit.py             Audit query
│   │   │   ├── plan.py              DAG topology visualization
│   │   │   ├── run.py               Execute workflow
│   │   │   ├── report.py            Generate report
│   │   │   ├── docs.py              Launch VitePress docs site
│   │   │   ├── knowledge.py         Knowledge management (CRUD + search + semantic search)
│   │   │   ├── learn.py             Learning engine (stats / recommendations / trajectories / patterns)
│   │   │   └── update.py            Update source & deps (git pull + pip install)
│   │   └── tests/
│   │
│   ├── mcp/                         MCP Server
│   │   ├── harness_mcp_server.py    25 MCP tools
│   │   └── tests/
│   │
│   ├── dashboard/                   Visualization Dashboard
│   │   ├── app.py                   FastAPI backend (35 APIs)
│   │   └── frontend.html            Frontend UI (10 tabs)
│   │
│   ├── hooks/                       Built-in Hooks
│   │   ├── hook-session-init.py     SessionStart hook
│   │   ├── hook-task-audit.py       Stop hook (audit record)
│   │   ├── hook-compliance-scan.py  PostToolUse hook (compliance scan)
│   │   ├── hook-guardrails-pii.py   PostToolUse hook (PII detection)
│   │   ├── hook-prompt-guardrails.py UserPromptSubmit hook
│   │   ├── hook-gate-pre-write.py   PreToolUse hook (gate intercept before file write)
│   │   └── tests/
│   │
│   ├── agents/                      Agent module
│   │   ├── harness_agents/
│   │   │   ├── coding_agents.py     4 coding roles
│   │   │   ├── orchestrator.py      Multi-Agent orchestration
│   │   │   ├── react_runtime.py     ReAct reasoning execution
│   │   │   └── tool_executor.py     Tool executor
│   │   └── tests/
│   │
│   ├── sdk-python/                  Python SDK
│   │   ├── harness_sdk/
│   │   │   ├── decorators.py        @harness_agent / @simple_agent
│   │   │   ├── hooks.py             Lifecycle hooks
│   │   │   ├── client.py            HarnessClient
│   │   │   └── agent.py             Agent interface
│   │   └── tests/
│   │
│   ├── sdk-typescript/              TypeScript SDK
│   │   ├── src/
│   │   │   ├── agent.ts             defineAgent / simpleAgent
│   │   │   ├── hooks.ts             Lifecycle hooks
│   │   │   ├── client.ts            HarnessClient
│   │   │   └── types.ts             Type definitions
│   │   └── tests/
│   │
│   └── vscode-extension/            VS Code extension
│
├── skills/                          Skills directory
│   ├── auto-audit/                  Auto-audit Skill
│   │   ├── SKILL.md                 Skill declaration
│   │   ├── audit_report.py          Execution script
│   │   └── tests/
│   ├── auto-review/                 Auto-review Skill
│   │   ├── SKILL.md
│   │   ├── review_gate.py
│   │   └── tests/
│   ├── auto-verify/                 Auto-verify Skill
│   │   ├── SKILL.md
│   │   ├── verify.py
│   │   └── tests/
│   └── harness-bridge/              Bridge Skill
│       ├── SKILL.md
│       └── bridge.py
│
├── .harness/
│   ├── active_profile               Active Profile marker (committed to Git)
│   ├── active_adapter               Active adapter marker (committed to Git)
│   ├── profiles/
│   │   ├── basic.yaml               Basic Profile (LOOSE + 3 steps + 2 hooks)
│   │   ├── default.yaml             Default Profile (HYBRID + 5 steps + 3 hooks)
│   │   └── enterprise.yaml          Enterprise Profile (STRICT + 5 steps + 9 hooks)
│   └── audit/                       Audit logs (gitignored)
│
├── examples/                        Examples
│   ├── simple-agent/                Single-Agent minimal
│   ├── multi-agent/                 Multi-Agent DAG orchestration
│   ├── hermes-bridge/               Hermes integration
│   └── custom-rules/                Custom rules
│
├── docs/                            Documentation
│   ├── architecture-design.md       Architecture design
│   ├── 12-脚手架化改造差距分析.md
│   ├── 13-脚手架化开发计划.md
│   ├── 14-第一期交付总结.md
│   └── 15-完整实现总结.md
│
├── playground/                      VitePress docs site
│   ├── docs/                        Doc pages
│   └── demo_*.py                    Demo scripts
│
├── workflows/                       Workflow examples
│   └── basex-examples.yaml
│
├── README.md
├── LICENSE
├── package.json
└── .github/workflows/ci.yml
```

---

## Tests

```bash
# Core tests
cd packages/core
PYTHONPATH=. pytest tests/ -v

# New acceptance tests (S-1~S-5 + E-1~E-10)
pytest tests/test_adapter_registry_s1.py tests/test_governance_semantics_s2.py \
       tests/test_governance_layering_s3.py tests/test_knowledge_activate_s4.py \
       tests/test_yield_detection_s5.py -v
```

**1644 tests collected, 1576 passed, 18 pre-existing failures, 0 new failures** ✅

---

## License

MIT
