/**
 * harness-sdk TypeScript HarnessClient
 *
 * 与 Python SDK 的 harness_sdk.client 对齐:
 *  - HarnessClient → 编排/合规/审计一站式
 *  - createClient → 便捷创建
 *
 * 支持 stdio 和 HTTP 两种 MCP 传输方式：
 *  - stdio（默认）: 通过子进程与 MCP Server 通信
 *  - http: 通过 HTTP 与 Dashboard/远程 MCP Server 通信
 */

import {
  DAGWorkflow,
  TaskResult,
  Artifact,
  ComplianceResult,
  AuditEntry,
  AuditStats,
  Recommendation,
  ExecutionTrace,
  KnowledgeQueryResult,
  HarnessConfig,
} from './types';

import { IMcpTransport, StdioTransport, HttpTransport } from './transport';

// ─── Client 配置 ────────────────────────────────────────

export interface HarnessClientConfig {
  /** 项目名称 */
  projectName?: string;
  /** 传输模式: "stdio"（默认）或 "http" */
  transport?: 'stdio' | 'http';
  /** MCP Server 地址（仅 HTTP 模式，默认 http://localhost:8765） */
  serverUrl?: string;
  /** MCP Server 命令（仅 stdio 模式，默认 "python3"） */
  mcpCommand?: string;
  /** MCP Server 参数（仅 stdio 模式） */
  mcpArgs?: string[];
  /** 学习开关 */
  learningEnabled?: boolean;
  /** 审计开关 */
  auditEnabled?: boolean;
}

// ─── Harness Client ────────────────────────────────────

export class HarnessClient {
  private _config: HarnessClientConfig;
  private _transport: IMcpTransport;
  private _nextId: number = 1;

  constructor(config: HarnessClientConfig) {
    this._config = config;

    // 根据配置选择传输方式
    const transportMode = config.transport || 'stdio';
    if (transportMode === 'http') {
      this._transport = new HttpTransport(config.serverUrl);
    } else {
      this._transport = new StdioTransport(
        config.mcpCommand || 'python3',
        config.mcpArgs || ['packages/mcp/harness_mcp_server.py'],
      );
    }
  }

  // ─── DAG 编排 ──

  /**
   * 运行 DAG 工作流
   */
  async runWorkflow(
    workflow: DAGWorkflow,
    inputs?: Record<string, unknown>,
  ): Promise<Record<string, TaskResult>> {
    return this._callMcp('harness_run', {
      workflow_yaml: JSON.stringify(workflow),
    });
  }

  /**
   * 运行单个 Agent 任务
   */
  async runSingleTask(
    agentId: string,
    task: string,
    context?: Record<string, unknown>,
  ): Promise<TaskResult> {
    return this._callMcp('harness_run', {
      workflow_yaml: JSON.stringify({
        nodes: [{ id: 'single-task', agent_type: agentId, task }],
        edges: [],
      }),
    });
  }

  // ─── 合规 ──

  /**
   * 合规扫描
   */
  async complianceScan(
    path: string,
    packs?: string[],
  ): Promise<ComplianceResult[]> {
    return this._callMcp('harness_check', {
      path,
      pack_names: packs,
    });
  }

  // ─── 审计 ──

  /**
   * 审计查询
   */
  async auditQuery(params?: {
    query?: string;
    limit?: number;
  }): Promise<AuditEntry[]> {
    return this._callMcp('harness_audit', {
      query: params?.query || '',
      limit: params?.limit || 50,
    });
  }

  // ─── 统计 ──

  /**
   * Harness 全局统计
   */
  async stats(): Promise<Record<string, unknown>> {
    return this._callMcp('harness_status', {});
  }

  // ─── 内部 MCP 调用 ──

  private async _callMcp(method: string, params: Record<string, unknown>): Promise<any> {
    const response = await this._transport.call({
      jsonrpc: '2.0',
      id: this._nextId++,
      method,
      params,
    });

    if (response.error) {
      throw new Error(`MCP Server error: ${response.error.message}`);
    }
    return response.result;
  }

  // ─── 生命周期 ──

  /** 关闭客户端和传输连接 */
  close(): void {
    this._transport.close();
  }
}

// ─── 便捷函数 ────────────────────────────────────────

export function createClient(config?: HarnessClientConfig): HarnessClient {
  return new HarnessClient(config || {});
}
