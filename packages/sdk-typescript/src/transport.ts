/**
 * harness-sdk MCP Transport Layer
 *
 * 抽象 MCP 通信传输，支持两种模式：
 * 1. StdioTransport — 通过子进程 stdin/stdout 传递 JSON-RPC（默认，适用于 CLI MCP Server）
 * 2. HttpTransport — 通过 HTTP POST 传递 JSON-RPC（适用于 Dashboard / 远程 MCP Server）
 */

// ─── MCP 请求/响应类型 ──────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: '2.0';
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: '2.0';
  id: number;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

// ─── Transport 接口 ─────────────────────────────────────

export interface IMcpTransport {
  /** 发送 JSON-RPC 请求并等待响应 */
  call(request: JsonRpcRequest): Promise<JsonRpcResponse>;

  /** 关闭传输连接 */
  close(): void;
}

// ─── StdioTransport ─────────────────────────────────────

export class StdioTransport implements IMcpTransport {
  private _process: import('child_process').ChildProcess | null = null;
  private _buffer: string = '';
  private _pending: Map<number, {
    resolve: (response: JsonRpcResponse) => void;
    reject: (error: Error) => void;
  }> = new Map();
  private _nextId: number = 1;
  private _command: string;
  private _args: string[];

  /**
   * @param command 启动 MCP Server 的命令（如 "python3"）
   * @param args 命令参数（如 ["packages/mcp/harness_mcp_server.py"]）
   */
  constructor(command: string, args: string[] = []) {
    this._command = command;
    this._args = args;
  }

  private _ensureProcess(): void {
    if (this._process && !this._process.killed) {
      return;
    }

    const { spawn } = require('child_process');
    const proc = spawn(this._command, this._args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env },
    }) as import('child_process').ChildProcess;
    this._process = proc;

    proc.stdout!.on('data', (chunk: Buffer) => {
      this._buffer += chunk.toString('utf-8');
      this._processBuffer();
    });

    if (proc.stderr) {
      proc.stderr.on('data', (chunk: Buffer) => {
        console.error(`[harness MCP] ${chunk.toString('utf-8').trim()}`);
      });
    }

    proc.on('error', (err: Error) => {
      console.error(`[harness MCP] Process error: ${err.message}`);
    });

    proc.on('exit', (code: number | null) => {
      if (code !== 0 && code !== null) {
        console.error(`[harness MCP] Process exited with code ${code}`);
      }
      for (const [id, pending] of this._pending) {
        pending.reject(new Error(`MCP Server process exited with code ${code}`));
        this._pending.delete(id);
      }
      this._process = null;
    });
  }

  private _processBuffer(): void {
    // JSON-RPC over stdio: 每个 JSON 对象占一行
    let newlineIdx: number;
    while ((newlineIdx = this._buffer.indexOf('\n')) !== -1) {
      const line = this._buffer.substring(0, newlineIdx).trim();
      this._buffer = this._buffer.substring(newlineIdx + 1);

      if (!line) continue;

      try {
        const response: JsonRpcResponse = JSON.parse(line);
        const pending = this._pending.get(response.id);
        if (pending) {
          this._pending.delete(response.id);
          pending.resolve(response);
        }
      } catch {
        // 非法 JSON → 忽略
      }
    }
  }

  async call(request: JsonRpcRequest): Promise<JsonRpcResponse> {
    this._ensureProcess();

    return new Promise<JsonRpcResponse>((resolve, reject) => {
      const id = this._nextId++;
      request.id = id;

      const timeoutMs = 30000; // 30s 超时
      const timer = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error(`MCP request timed out after ${timeoutMs}ms: ${request.method}`));
      }, timeoutMs);

      this._pending.set(id, {
        resolve: (response) => {
          clearTimeout(timer);
          resolve(response);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });

      const message = JSON.stringify(request) + '\n';
      this._process!.stdin!.write(message, (err?: Error | null) => {
        if (err) {
          this._pending.delete(id);
          clearTimeout(timer);
          reject(new Error(`Failed to write to MCP Server stdin: ${err.message}`));
        }
      });
    });
  }

  close(): void {
    if (this._process && !this._process.killed) {
      this._process.kill();
      this._process = null;
    }
    for (const [, pending] of this._pending) {
      pending.reject(new Error('Transport closed'));
    }
    this._pending.clear();
  }
}

// ─── HttpTransport ──────────────────────────────────────

export class HttpTransport implements IMcpTransport {
  private _serverUrl: string;

  constructor(serverUrl: string = 'http://localhost:8765') {
    this._serverUrl = serverUrl;
  }

  async call(request: JsonRpcRequest): Promise<JsonRpcResponse> {
    const response = await fetch(this._serverUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`MCP Server error: ${response.status} ${response.statusText}`);
    }

    const data = (await response.json()) as JsonRpcResponse;
    if (data.error) {
      throw new Error(`MCP Server error: ${data.error.message}`);
    }
    return data;
  }

  close(): void {
    // HTTP 无连接状态，无需关闭
  }
}
