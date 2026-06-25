# Auto Test 示例

> 代码变更后自动运行相关测试

**文档介绍**见 VitePress Demo 页面 [Auto Test](../../playground/docs/demo/auto-test.md)——代码片段 + 预期输出 + 配置说明。本目录是可运行的脚本。

## 功能

当使用 Write/Edit 修改代码文件后，自动检测并运行相关测试：

- Python 文件 → `pytest -v`
- JavaScript/TypeScript → `npm test`
- Go 文件 → `go test ./...`
- Java/Kotlin → `./gradlew test`

## 使用方法

```bash
# 复制到项目
cp examples/auto-test/hook-auto-test.py your-project/hooks/

# 在 profile 中配置
hooks:
  post_tool_use:
    - type: script
      command: "python3 hooks/hook-auto-test.py"
```

## 示例输出

```
🧪 检测到代码变更: src/utils.py
   运行测试: python3 -m pytest -v
✅ 测试通过
```

## 自定义

修改 `detect_test_command()` 函数以支持更多语言或自定义测试命令。
