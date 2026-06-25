# Lint Check 示例

> 代码变更后自动检查代码质量

**文档介绍**见 VitePress Demo 页面 [Lint Check](../../playground/docs/demo/lint-check.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 功能

当使用 Write/Edit 修改代码文件后，自动运行相应的 lint 工具：

- **Python** → `ruff check` 或 `flake8`
- **JavaScript/TypeScript** → `eslint`
- **Go** → `gofmt`

## 使用方法

```bash
# 复制到项目
cp examples/lint-check/hook-lint-check.py your-project/hooks/

# 在 profile 中配置
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-lint-check.py"
```

## 示例输出

### 通过
```
🔍 检查代码质量: src/utils.py
   运行: ruff check src/utils.py
✅ 代码质量检查通过
```

### 有问题
```
🔍 检查代码质量: src/utils.py
   运行: ruff check src/utils.py
⚠️  发现代码质量问题
   src/utils.py:10:5: F401 `os` imported but unused
   src/utils.py:15:1: E302 expected 2 blank lines, found 1
   ... 还有 3 个问题
```

## 前置要求

确保项目中已安装相应的 lint 工具：

```bash
# Python
pip install ruff  # 或 flake8

# JavaScript/TypeScript
npm install eslint

# Go
# gofmt 通常已内置
```

## 自定义

修改 `detect_lint_command()` 函数以：
- 支持更多语言
- 使用自定义 lint 配置
- 添加自动修复功能

## 组合使用

可以与其他 hook 组合使用：

```yaml
hooks:
  post_tool_use:
    # 1. 先检查代码质量
    - type: script
      command: "python3 hooks/hook-lint-check.py"
    
    # 2. 再运行测试
    - type: script
      command: "python3 hooks/hook-auto-test.py"
    
    # 3. 最后同步 CodeGraph
    - type: script
      command: "python3 hooks/hook-codegraph-sync.py"
```
