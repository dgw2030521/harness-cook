/**
 * harness-sdk TypeScript — Universal Agent Harness SDK
 *
 * Agent 决策执行，Harness 稳定约束。
 *
 * TypeScript SDK 为 nextX 等产品层提供类型安全的 Harness 接入:
 *  - defineAgent() → 定义 + 注册 Agent
 *  - Lifecycle Hooks → before/after/onError 拦截
 *  - HarnessClient → 编排/合规/审计一站式
 *
 * 用法:
 *   import { defineAgent, HarnessClient } from 'harness-sdk';
 *
 *   const reviewer = defineAgent({
 *     name: 'code-reviewer',
 *     capabilities: ['perceive', 'reason'],
 *     constraints: { maxChanges: 50, noDestructive: true },
 *   }, async (task, ctx) => {
 *     // ... Agent 业务逻辑 ...
 *     return { status: 'completed', artifacts: [] };
 *   });
 */

// ─── 类型导出 ────────────────────────────────────────

export {
  AgentCapability,
  AgentType,
  TaskStatus,
  GateMode,
  ComplianceCategory,
  GuardrailAction,
  KnowledgeType,
  KnowledgeScope,
  NegotiationEventType,
  BusEventType,
} from './types';

// ─── 核心接口导出 ────────────────────────────────────

export type {
  AgentDefinition,
  TaskResult,
  Artifact,
  AgentConstraints,
  HookContext,
  HookResult,
  DAGNode,
  DAGEdge,
  DAGWorkflow,
  SchedulePlan,
  ComplianceResult,
  AuditEntry,
  AuditStats,
  Recommendation,
  BusEvent,
  KnowledgeEntry,
  KnowledgeQuery,
  KnowledgeQueryResult,
} from './types';

// ─── Agent 定义 ──────────────────────────────────────

export { defineAgent, simpleAgent, DecoratedAgent } from './agent';

// ─── 生命周期钩子 ────────────────────────────────────

export {
  Hook,
  HookType,
  beforeHook,
  afterHook,
  errorHook,
  HookChain,
} from './hooks';

// ─── Harness Client ──────────────────────────────────

export { HarnessClient, HarnessClientConfig, createClient } from './client';