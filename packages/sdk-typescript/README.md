# harness-sdk (TypeScript)

harness-cook 的 TypeScript SDK，用于在 Node.js / 前端工程中接入治理能力。完整介绍见根目录 [README](../../README.md)。

## 定位

为 TypeScript / JavaScript 生态提供与 Python SDK 对等的程序化接入入口，便于在前端工程、Node 服务、Electron 应用中复用同一套治理规则。

## 安装

```bash
pnpm add harness-sdk
# 或
npm install harness-sdk
```

## 开发

```bash
cd packages/sdk-typescript
pnpm install
pnpm build
```

> 程序化 API 细节随版本演进，使用前请结合根 [README](../../README.md) 与 [docs/](../../docs/) 设计文档。
