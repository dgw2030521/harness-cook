# update — 一键更新

> git pull 拉取最新代码 + pip install -e 重新安装依赖

## 用法

```bash
# 默认更新（git pull + pip install）
harness update

# 只 git pull，跳过安装
harness update --skip-install

# 显示完整输出（git/pip 详细日志）
harness update --verbose
```

## 五步更新流程

| Step | 名称 | 说明 | 退出码 |
|------|------|------|--------|
| 1/5 | 定位源码目录 | `HARNESS_COOK_ROOT` env → 脚本位置推导 → 验证 git 仓库 | 1（不存在/非 git） |
| 2/5 | 检查工作区状态 | `git status --porcelain` 检查未提交修改 | 1（有修改 → 提示先提交） |
| 3/5 | git pull | `git pull origin <current_branch>` | 1（pull 失败） / 2（Already up to date） |
| 4/5 | pip install -e | 重新安装 `packages/core` + `packages/cli` | 可跳过（`--skip-install`） |
| 5/5 | 验证更新 | 记录旧版本 → 新版本对比 | — |

## 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--verbose` | 显示 git/pip 完整输出 | ❌ |
| `--skip-install` | 只 git pull，跳过 pip install -e | ❌ |

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 更新成功 |
| 1 | 更新失败（目录不存在/非 git/有未提交修改/pull 失败） |
| 2 | 无需更新（本地已是最新版本） |

## 源码目录定位

```
HARNESS_COOK_ROOT env  →  脚本位置推导  →  当前工作目录
```

脚本位置推导路径：`__file__ = .../packages/cli/cli_commands/update.py` → `parent(4) = harness-cook/`

---

← [deactivate](/cli/deactivate) · [命令总览](/cli/) · → [version](/cli/version)
