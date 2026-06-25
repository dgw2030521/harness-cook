# harness-cli

harness-cook 的命令行工具，注册 `harness` 命令。完整介绍见根目录 [README](../../README.md)。

## 安装

```bash
pip install harness-cli
# 或随主项目一键安装：在仓库根目录执行 ./install.sh
```

## 常用命令

```bash
harness version                              # 查看版本
harness activate                             # 一键激活（默认 Claude Code）
harness activate --agent hermes              # 部署到 Hermes
harness activate --agent cursor              # 部署到 Cursor IDE
harness activate --agent copilot-cli         # 部署到 Copilot CLI
harness dashboard                            # 启动可视化看板
```

`activate` 会：将 Profile 翻译为目标 Agent 原生格式（settings.json / MCP 配置 / function calling）并写入，同时安装 git pre-commit hook 作为兜底。

## 开发

```bash
cd packages/cli
pip install -e .[dev]
```

```
