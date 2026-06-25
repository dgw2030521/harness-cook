/**
 * harness-sdk TypeScript 测试
 */

import {
  defineAgent,
  simpleAgent,
  DecoratedAgent,
  beforeHook,
  afterHook,
  errorHook,
  HookChain,
  HookType,
  HookResult,
  HarnessClient,
  createClient,
  AgentCapability,
  GateMode,
} from '../src/index';

// ─── defineAgent 测试 ────────────────────────────────

describe('defineAgent', () => {
  test('基本定义+执行', async () => {
    const agent = defineAgent({
      name: 'test-reviewer',
      capabilities: [AgentCapability.PERCEIVE, AgentCapability.REASON],
      autoRegister: false,
    }, (task, ctx) => ({
      taskId: 't-1',
      agentId: 'test-reviewer',
      status: 'completed',
      artifacts: [],
      durationMs: 100,
      tokensUsed: 50,
      metadata: {},
    }));

    expect(agent.definition.name).toBe('test-reviewer');
    const result = await agent.execute('review code', { taskId: 't-1' });
    expect(result.status).toBe('completed');
  });

  test('带约束定义', async () => {
    const agent = defineAgent({
      name: 'constrained-agent',
      constraints: { maxChanges: 10, noDestructive: true },
      autoRegister: false,
    }, (task, ctx) => ({
      taskId: 't-1',
      agentId: 'constrained-agent',
      status: 'completed',
      artifacts: [],
      durationMs: 50,
      tokensUsed: 0,
      metadata: {},
    }));

    expect(agent.constraints.noDestructive).toBe(true);
    expect(agent.constraints.maxChanges).toBe(10);
  });
});

// ─── simpleAgent 测试 ────────────────────────────────

describe('simpleAgent', () => {
  test('极简版定义', async () => {
    const worker = simpleAgent('simple-worker', (task, ctx) => ({
      taskId: 't-1',
      agentId: 'simple-worker',
      status: 'completed',
      artifacts: [],
      durationMs: 30,
      tokensUsed: 0,
      metadata: {},
    }));

    expect(worker.definition.name).toBe('simple-worker');
    expect(worker.constraints.noDestructive).toBe(true);
  });
});

// ─── Hooks 测试 ────────────────────────────────────────

describe('Hooks', () => {
  test('beforeHook 注册+执行', () => {
    let callCount = 0;

    const hook = beforeHook((ctx) => {
      callCount++;
      expect(ctx.task).toBe('test task');
      return HookResult.CONTINUE;
    });

    const chain = new HookChain();
    chain.add(hook);

    const abortReason = chain.runBefore('test task', 'agent', 'a-1', {});
    expect(abortReason).toBeNull();
    expect(callCount).toBe(1);
  });

  test('HookChain stats', () => {
    const hook1 = beforeHook((ctx) => HookResult.CONTINUE);
    const hook2 = afterHook((ctx) => HookResult.CONTINUE);

    const chain = new HookChain();
    chain.add(hook1);
    chain.add(hook2);

    const stats = chain.stats();
    expect(stats.beforeHooks).toBe(1);
    expect(stats.afterHooks).toBe(1);
    expect(stats.totalHooks).toBe(2);
  });
});

// ─── Client 测试 ────────────────────────────────────────

describe('HarnessClient', () => {
  test('createClient 创建', () => {
    const client = createClient({ projectName: 'test' });
    expect(client).toBeDefined();
  });
});