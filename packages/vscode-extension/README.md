# harness-cook VS Code Extension

09号竞品报告指出"缺乏IDE集成"(vs SonarQude/CodeClimate有VS Code插件)。
本extension提供LSP诊断推送、命令面板操作、侧边栏可视化。

## 功能

| 命令 | 说明 |
|------|------|
| Harness Cook: Scan Compliance | 对当前文件运行合规扫描，推送诊断 |
| Harness Cook: Verify Audit Chain | 验证审计链完整性 |
| Harness Cook: Show Dependency Graph | 打开Webview显示依赖图 |
| Harness Cook: Show Call Graph | 打开Webview显示方法级调用图 |
| Harness Cook: Taint Analysis | 污点追踪，高亮source/sink |
| Harness Cook: Create Rollback Snapshot | 创建回滚快照 |
| Harness Cook: Restore from Snapshot | 从快照恢复 |

## 配置项

| Key | 默认值 | 说明 |
|-----|--------|------|
| serverUrl | http://localhost:8765 | Dashboard服务地址 |
| scanOnSave | false | 保存文件时自动扫描 |
| gateMode | hybrid | Gate模式(strict/hybrid/loose) |
| severityThreshold | medium | 最低显示严重度 |

## 安装

```bash
cd packages/vscode-extension
npm install
# VS Code中: Extensions → Install from VSIX
# 或开发模式: F5启动Extension Development Host
```

## 依赖

- harness-cook Dashboard需运行在 `serverUrl` 地址
- Dashboard API端点:
  - POST /api/scan — 合规扫描
  - GET /api/audit/verify — 审计链验证
  - GET /api/report/dependency-graph — 依赖图HTML
  - POST /api/call-graph — 调用图
  - POST /api/taint — 污点追踪
  - POST /api/rollback/snapshot — 创建快照
  - GET /api/rollback/list — 快照列表
  - POST /api/rollback/restore — 恢复快照