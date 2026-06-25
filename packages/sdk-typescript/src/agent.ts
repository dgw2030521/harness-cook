/**
 * harness-sdk TypeScript Agent 定义接口
 *
 * 与 Python SDK 的 harness_sdk.agent + harness_sdk.decorators 对齐:
 *  - defineAgent() → 完整版（定义+约束+门禁+handler）
 *  - simpleAgent() → 极简版（只需 name + handler）
 *  - DecoratedAgent → 包装后的 Agent 实例
 */

import {
  AgentCapability,
  AgentType,
  AgentDefinition,
  AgentConstraints,
  AgentPriority,
  GateMode,
  TaskResult,
  TaskStatus,
  Artifact,
} from './types';

/**
 * Agent handler 函数签名
 */
export type AgentHandler = (
  task: string,
  context: Record<string, unknown>,
) => Promise<TaskResult> | TaskResult;

/**
 * defineAgent 配置
 */
export interface DefineAgentConfig {
  name: string;
  capabilities?: AgentCapability[];
  agentType?: AgentType;
  constraints?: Partial<AgentConstraints>;
  gateMode?: GateMode;
  toolsets?: string[];
  maxRounds?: number;
  temperature?: number;
  systemPrompt?: string;
  autoRegister?: boolean;
}

/**
 * simpleAgent 配置（极简版）
 */
export interface SimpleAgentConfig {
  name: string;
  gateMode?: GateMode;
  toolsets?: string[];
  maxChanges?: number;
  noDestructive?: boolean;
  timeout?: number;
}

// ─── 内部 Registry ────────────────────────────────────

interface RegistryEntry {
  definition: AgentDefinition;
  handler: AgentHandler;
}

const _registry: Map<string, RegistryEntry> = new Map();

// ─── DecoratedAgent ────────────────────────────────────

export class DecoratedAgent {
  private _definition: AgentDefinition;
  private _handler: AgentHandler;
  private _constraints: AgentConstraints;
  private _gateMode: GateMode;

  constructor(
    definition: AgentDefinition,
    handler: AgentHandler,
    constraints: AgentConstraints,
    gateMode: GateMode,
  ) {
    this._definition = definition;
    this._handler = handler;
    this._constraints = constraints;
    this._gateMode = gateMode;
  }

  /** 执行 Agent 任务 */
  async execute(task: string, context: Record<string, unknown>): Promise<TaskResult> {
    // 约束前置检查
    const violations = this._preCheck(task, context);
    if (violations.length > 0) {
      const blocking = violations.filter(v => v.severity === 'blocking');
      if (blocking.length > 0) {
        return {
          taskId: (context.taskId as string) || '',
          agentId: this._definition.id,
          status: TaskStatus.Failed,
          artifacts: [],
          durationMs: 0,
          tokensUsed: 0,
          error: `约束违规: ${blocking[0].detail}`,
          metadata: { constraintViolations: violations },
        };
      }
    }

    // 调用 handler
    const result = await this._handler(task, context);
    return result;
  }

  /** 预估 Token 消耗 */
  estimateTokens(task: string): number {
    if (this._constraints.maxTokens > 0) {
      return Math.min(this._constraints.maxTokens, task.length * 4 + 500);
    }
    return task.length * 4 + 500;
  }

  get definition(): AgentDefinition { return this._definition; }
  get constraints(): AgentConstraints { return this._constraints; }
  get gateMode(): GateMode { return this._gateMode; }

  private _preCheck(task: string, context: Record<string, unknown>): Array<{type: string; detail: string; severity: string}> {
    const violations: Array<{type: string; detail: string; severity: string}> = [];

    // 破坏性操作检查
    if (this._constraints.noDestructive) {
      const destructiveKws = ['delete', 'drop', 'remove', 'force', 'rm -rf', 'truncate'];
      for (const kw of destructiveKws) {
        if (task.toLowerCase().includes(kw.toLowerCase())) {
          violations.push({
            type: 'destructive',
            detail: `破坏性操作被约束禁止: 检测到关键词 '${kw}'`,
            severity: 'blocking',
          });
        }
      }
    }

    return violations;
  }
}

// ─── 默认约束 ────────────────────────────────────────

function defaultConstraints(overrides?: Partial<AgentConstraints>): AgentConstraints {
  return {
    filePatterns: overrides?.filePatterns || [],
    maxChanges: overrides?.maxChanges || 20,
    requireReview: overrides?.requireReview || false,
    noDestructive: overrides?.noDestructive || true,
    timeout: overrides?.timeout || 300,
    priority: overrides?.priority || AgentPriority.NORMAL,
    allowedCommands: overrides?.allowedCommands || [],
    maxTokens: overrides?.maxTokens || 0,
  };
}

// ─── defineAgent ──────────────────────────────────────

/**
 * defineAgent —— 完整版 Agent 定义+注册
 *
 * 用法:
 *   const reviewer = defineAgent({
 *     name: 'code-reviewer',
 *     capabilities: [AgentCapability.PERCEIVE, AgentCapability.REASON],
 *     constraints: { maxChanges: 50, noDestructive: true },
 *     gateMode: GateMode.HYBRID,
 *   }, async (task, ctx) => {
 *     return { taskId: ctx.taskId, agentId: 'code-reviewer', status: 'completed', ... };
 *   });
 */
export function defineAgent(
  config: DefineAgentConfig,
  handler: AgentHandler,
): DecoratedAgent {
  const capabilities = config.capabilities || [AgentCapability.PERCEIVE, AgentCapability.REASON];
  const constraints = defaultConstraints(config.constraints);
  const gateMode = config.gateMode || GateMode.HYBRID;
  const toolsets = config.toolsets || [];
  const maxRounds = config.maxRounds || 15;
  const temperature = config.temperature || 0.2;
  const systemPrompt = config.systemPrompt || '';

  const agentId = config.name.replace(/\s+/g, '-').toLowerCase();

  const definition: AgentDefinition = {
    id: agentId,
    name: config.name,
    capabilities,
    toolsets,
    agentType: config.agentType,
    maxRounds,
    temperature,
    systemPrompt,
    metadata: {
      constraints,
      gateMode,
      decorated: true,
    },
  };

  const agent = new DecoratedAgent(definition, handler, constraints, gateMode);

  // 自动注册
  if (config.autoRegister !== false) {
    _registry.set(agentId, { definition, handler });
  }

  return agent;
}

// ─── simpleAgent ──────────────────────────────────────

/**
 * simpleAgent —— 极简版 Agent 定义
 *
 * 只需 name + handler，其余自动生成默认值。
 * 适合入门用户快速接入 Harness。
 *
 * 用法:
 *   const worker = simpleAgent('my-worker', async (task, ctx) => {
 *     return { taskId: 't-1', agentId: 'my-worker', status: 'completed', ... };
 *   });
 */
export function simpleAgent(
  name: string,
  handler: AgentHandler,
  config?: SimpleAgentConfig,
): DecoratedAgent {
  return defineAgent({
    name,
    capabilities: [AgentCapability.PERCEIVE, AgentCapability.REASON],
    constraints: {
      maxChanges: config?.maxChanges || 20,
      noDestructive: config?.noDestructive ?? true,
      timeout: config?.timeout || 300,
    },
    gateMode: config?.gateMode || GateMode.HYBRID,
    toolsets: config?.toolsets || ['terminal', 'file'],
    autoRegister: true,
  }, handler);
}

// ─── Registry 查询 ────────────────────────────────────

export function getAgent(agentId: string): RegistryEntry | undefined {
  return _registry.get(agentId);
}

export function listAgents(): Array<{id: string; name: string; capabilities: string[]}> {
  return Array.from(_registry.entries()).map(([id, entry]) => ({
    id,
    name: entry.definition.name,
    capabilities: entry.definition.capabilities.map(c => c),
  }));
}