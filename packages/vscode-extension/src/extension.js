/**
 * harness-cook VS Code Extension — AI Agent Compliance Diagnostics
 *
 * 09号竞品报告指出"缺乏IDE集成"(vs SonarQube/CodeClimate有VS Code插件)。
 * 本脚手架提供:
 *   1. LSP诊断推送(合规扫描结果→编辑器红线/黄线)
 *   2. 命令面板操作(扫描/审计验证/依赖图/调用图/污点分析/回滚)
 *   3. 侧边栏可视化(DSM方阵/依赖图HTML)
 *
 * 通信方式: HTTP → harness-cook Dashboard (localhost:8765)
 */

const vscode = require('vscode');

// ─── 激活 ────────────────────────────────────────────

function activate(context) {
    console.log('Harness Cook extension activated');

    const serverUrl = () => vscode.workspace.getConfiguration('harness-cook').get('serverUrl', 'http://localhost:8765');

    // ─── 命令注册 ──────────────────────────────────────

    // 合规扫描
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.scan', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) { vscode.window.showWarningMessage('No active editor'); return; }

            const filePath = editor.document.uri.fsPath;
            const language = editor.document.languageId;

            try {
                const results = await fetch(`${serverUrl()}/api/scan`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_path: filePath, language }),
                });
                const data = await results.json();
                renderDiagnostics(editor.document.uri, data.results || []);
                const failed = (data.results || []).filter(r => !r.passed).length;
                vscode.window.showInformationMessage(`Scan complete: ${data.results.length} rules, ${failed} violations`);
            } catch (e) {
                vscode.window.showErrorMessage(`Scan failed: ${e.message}`);
            }
        })
    );

    // 审计链验证
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.showAuditChain', async () => {
            try {
                const resp = await fetch(`${serverUrl()}/api/audit/verify`);
                const data = await resp.json();
                if (data.valid) {
                    vscode.window.showInformationMessage(`Audit chain valid (${data.entries} entries, last hash: ${data.last_hash})`);
                } else {
                    vscode.window.showErrorMessage(`Audit chain BROKEN at entry ${data.broken_at}`);
                }
            } catch (e) {
                vscode.window.showErrorMessage(`Audit verify failed: ${e.message}`);
            }
        })
    );

    // 依赖图
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.showDependencyGraph', async () => {
            const workspaceRoot = vscode.workspace.rootPath;
            if (!workspaceRoot) { vscode.window.showWarningMessage('No workspace open'); return; }
            try {
                const resp = await fetch(`${serverUrl()}/api/report/dependency-graph?root=${encodeURIComponent(workspaceRoot)}`);
                const html = await resp.text();
                const panel = vscode.window.createWebviewPanel('depGraph', 'Dependency Graph', vscode.ViewColumn.Two);
                panel.webview.html = html;
            } catch (e) {
                vscode.window.showErrorMessage(`Dependency graph failed: ${e.message}`);
            }
        })
    );

    // 调用图
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.showCallGraph', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) { vscode.window.showWarningMessage('No active editor'); return; }
            try {
                const resp = await fetch(`${serverUrl()}/api/call-graph`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_path: editor.document.uri.fsPath, language: editor.document.languageId }),
                });
                const data = await resp.json();
                const panel = vscode.window.createWebviewPanel('callGraph', 'Call Graph', vscode.ViewColumn.Two);
                panel.webview.html = renderCallGraphHtml(data);
            } catch (e) {
                vscode.window.showErrorMessage(`Call graph failed: ${e.message}`);
            }
        })
    );

    // 点分析
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.taintAnalysis', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) { vscode.window.showWarningMessage('No active editor'); return; }
            try {
                const resp = await fetch(`${serverUrl()}/api/taint`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_path: editor.document.uri.fsPath, language: editor.document.languageId }),
                });
                const data = await resp.json();
                if (data.findings && data.findings.length > 0) {
                    vscode.window.showWarningMessage(`Taint: ${data.findings.length} source→sink flows detected`);
                    // 渲染污点标记到编辑器
                    renderTaintHighlights(editor, data.findings);
                } else {
                    vscode.window.showInformationMessage('Taint: no source→sink flows detected');
                }
            } catch (e) {
                vscode.window.showErrorMessage(`Taint analysis failed: ${e.message}`);
            }
        })
    );

    // 回滚快照
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.rollbackSnapshot', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) return;
            try {
                const resp = await fetch(`${serverUrl()}/api/rollback/snapshot`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_paths: [editor.document.uri.fsPath] }),
                });
                const data = await resp.json();
                vscode.window.showInformationMessage(`Snapshot created: ${data.snapshot_id}`);
            } catch (e) {
                vscode.window.showErrorMessage(`Snapshot failed: ${e.message}`);
            }
        })
    );

    // 回滚恢复
    context.subscriptions.push(
        vscode.commands.registerCommand('harness-cook.rollbackRestore', async () => {
            try {
                const resp = await fetch(`${serverUrl()}/api/rollback/list`);
                const data = await resp.json();
                const items = (data.snapshots || []).map(s => ({
                    label: `Snapshot ${s.snapshot_id} (${s.created_at})`,
                    description: `Files: ${s.file_count}`,
                    snapshotId: s.snapshot_id,
                }));
                const picked = await vscode.window.showQuickPick(items);
                if (!picked) return;
                const restoreResp = await fetch(`${serverUrl()}/api/rollback/restore`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ snapshot_id: picked.snapshotId }),
                });
                const restoreData = await restoreResp.json();
                vscode.window.showInformationMessage(`Restored snapshot ${picked.snapshotId}: ${restoreData.restored_files} files`);
            } catch (e) {
                vscode.window.showErrorMessage(`Restore failed: ${e.message}`);
            }
        })
    );

    // ─── 保存时扫描 ────────────────────────────────────

    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(doc => {
            const config = vscode.workspace.getConfiguration('harness-cook');
            if (config.get('scanOnSave', false)) {
                vscode.commands.executeCommand('harness-cook.scan');
            }
        })
    );
}

// ─── 诊断渲染 ────────────────────────────────────────

const diagnosticCollection = vscode.languages.createDiagnosticCollection('harness-cook');

function renderDiagnostics(uri, results) {
    const diagnostics = [];
    const threshold = vscode.workspace.getConfiguration('harness-cook').get('severityThreshold', 'medium');
    const severityMap = { high: vscode.DiagnosticSeverity.Error, medium: vscode.DiagnosticSeverity.Warning, low: vscode.DiagnosticSeverity.Information };
    const minSeverity = severityMap[threshold] || vscode.DiagnosticSeverity.Warning;

    for (const r of results) {
        if (r.passed) continue;
        const sev = severityMap[r.severity] || vscode.DiagnosticSeverity.Warning;
        if (sev > minSeverity) continue;  // higher number = lower severity

        const range = new vscode.Range(
            r.line ? r.line - 1 : 0, 0,
            r.line ? r.line - 1 : 0, 200
        );
        const msg = `${r.rule_id}: ${r.findings.join('; ')}`;
        diagnostics.push(new vscode.Diagnostic(range, msg, sev));
    }
    diagnosticCollection.set(uri, diagnostics);
}

// ─── 污点高亮 ────────────────────────────────────────

function renderTaintHighlights(editor, findings) {
    const decorations = [];
    const sourceType = vscode.window.createTextEditorDecorationType({
        backgroundColor: 'rgba(255,100,100,0.3)',
        overviewColor: 'red',
        gutterIconPath: undefined,
    });
    const sinkType = vscode.window.createTextEditorDecorationType({
        backgroundColor: 'rgba(255,200,100,0.3)',
        overviewColor: 'orange',
    });

    const sources = [];
    const sinks = [];
    for (const f of findings) {
        if (f.source_line > 0) sources.push(new vscode.Range(f.source_line - 1, 0, f.source_line - 1, 200));
        if (f.sink_line > 0) sinks.push(new vscode.Range(f.sink_line - 1, 0, f.sink_line - 1, 200));
    }
    editor.setDecorations(sourceType, sources);
    editor.setDecorations(sinkType, sinks);
}

// ─── 调用图HTML ────────────────────────────────────────

function renderCallGraphHtml(data) {
    const nodes = data.nodes || {};
    const edges = data.edges || {};
    let svg = '';
    const positions = {};
    let idx = 0;
    for (const name in nodes) {
        const x = (idx % 8) * 100 + 50;
        const y = Math.floor(idx / 8) * 80 + 50;
        positions[name] = { x, y };
        svg += `<circle cx="${x}" cy="${y}" r="15" fill="#4ecdc4" stroke="#16213e" stroke-width="2"/>`;
        svg += `<text x="${x}" y="${y+25}" fill="#eee" font-size="10" text-anchor="middle">${name}</text>`;
        idx++;
    }
    for (const caller in edges) {
        for (const callee of edges[caller]) {
            if (positions[caller] && positions[callee]) {
                svg += `<line x1="${positions[caller].x}" y1="${positions[caller].y}" x2="${positions[callee].x}" y2="${positions[callee].y}" stroke="#555" stroke-width="1"/>`;
            }
        }
    }
    return `<!DOCTYPE html><html><head><style>body{background:#1a1a2e;color:#eee;font-family:sans-serif;padding:20px}svg{border:1px solid #333;border-radius:8px}</style></head><body><h1>Call Graph</h1><svg width="900" height="500">${svg}</svg></body></html>`;
}

// ─── 去激活 ────────────────────────────────────────────

function deactivate() {
    diagnosticCollection.dispose();
}

module.exports = { activate, deactivate };