/**
 * harness-sdk TypeScript 生命周期钩子
 *
 * 与 Python SDK 的 harness_sdk.hooks 对齐:
 *  - Hook / HookType / HookContext / HookResult 类型
 *  - beforeHook / afterHook / errorHook 装饰器式注册
 *  - HookChain 执行链
 */

import {
  HookType,
  HookContext,
  HookResult,
  TaskResult,
} from './types';

/**
 * Hook 函数签名
 */
export type HookFn = (context: HookContext) => HookResult;

/**
 * Hook 对象——包含函数 + 类型 + 名称
 */
export class Hook {
  private _fn: HookFn;
  private _hookType: HookType;
  private _name: string;

  constructor(fn: HookFn, hookType: HookType, name?: string) {
    this._fn = fn;
    this._hookType = hookType;
    this._name = name || fn.name || 'anonymous';
  }

  call(context: HookContext): HookResult {
    try {
      context.hookType = this._hookType;
      return this._fn(context);
    } catch (e) {
      // Hook 异常不影响 Agent 执行
      return HookResult.CONTINUE;
    }
  }

  get name(): string { return this._name; }
  get hookType(): HookType { return this._hookType; }
}

/**
 * beforeHook —— 将函数注册为 before 钩子
 *
 * 用法:
 *   const logHook = beforeHook((ctx) => {
 *     console.log(`Agent ${ctx.agentName} starting: ${ctx.task}`);
 *     return HookResult.CONTINUE;
 *   });
 */
export function beforeHook(fn: HookFn): Hook {
  return new Hook(fn, HookType.BEFORE);
}

/**
 * afterHook —— 将函数注册为 after 钩子
 */
export function afterHook(fn: HookFn): Hook {
  return new Hook(fn, HookType.AFTER);
}

/**
 * errorHook —— 将函数注册为 on_error 钩子
 */
export function errorHook(fn: HookFn): Hook {
  return new Hook(fn, HookType.ON_ERROR);
}

/**
 * HookChain —— 按注册顺序依次执行多个 Hook
 */
export class HookChain {
  private _beforeHooks: Hook[] = [];
  private _afterHooks: Hook[] = [];
  private _errorHooks: Hook[] = [];

  add(hook: Hook): void {
    if (hook.hookType === HookType.BEFORE) {
      this._beforeHooks.push(hook);
    } else if (hook.hookType === HookType.AFTER) {
      this._afterHooks.push(hook);
    } else if (hook.hookType === HookType.ON_ERROR) {
      this._errorHooks.push(hook);
    }
  }

  /**
   * 运行 before 钩子链
   * Returns: null (全部通过) 或 ABORT 原因
   */
  runBefore(
    task: string,
    agentName: string,
    agentId: string,
    context: Record<string, unknown>,
  ): string | null {
    const ctx: HookContext = {
      task, agentName, agentId, context,
      hookType: HookType.BEFORE,
      metadata: {},
    };

    for (const hook of this._beforeHooks) {
      const result = hook.call(ctx);
      if (result === HookResult.ABORT) {
        return `Aborted by hook '${hook.name}'`;
      }
      if (result === HookResult.SKIP) {
        break;
      }
    }
    return null;
  }

  /**
   * 运行 after 钩子链
   */
  runAfter(
    result: TaskResult,
    task: string,
    agentName: string,
    agentId: string,
    context: Record<string, unknown>,
  ): void {
    const ctx: HookContext = {
      task, agentName, agentId, context, result,
      hookType: HookType.AFTER,
      metadata: {},
    };

    for (const hook of this._afterHooks) {
      const hookResult = hook.call(ctx);
      if (hookResult === HookResult.SKIP) break;
    }
  }

  /**
   * 运行 on_error 钩子链
   */
  runOnError(
    error: string,
    task: string,
    agentName: string,
    agentId: string,
    context: Record<string, unknown>,
  ): void {
    const ctx: HookContext = {
      task, agentName, agentId, context, error,
      hookType: HookType.ON_ERROR,
      metadata: {},
    };

    for (const hook of this._errorHooks) {
      const hookResult = hook.call(ctx);
      if (hookResult === HookResult.SKIP) break;
    }
  }

  /** 统计 */
  stats(): { beforeHooks: number; afterHooks: number; errorHooks: number; totalHooks: number } {
    return {
      beforeHooks: this._beforeHooks.length,
      afterHooks: this._afterHooks.length,
      errorHooks: this._errorHooks.length,
      totalHooks: this._beforeHooks.length + this._afterHooks.length + this._errorHooks.length,
    };
  }
}