"""
规则市场——社区共享的规则库

提供规则包的发现、下载、上传和管理功能。

## 使用方式

### 1. 从社区下载规则包

```python
from harness.rule_market import RuleMarket

market = RuleMarket()

# 列出可用的规则包
available_packs = market.list_available()

# 下载规则包
market.download("security-best-practices")

# 安装到本地
market.install("security-best-practices")
```

### 2. 上传自定义规则包

```python
from harness.rule_market import RuleMarket
from harness.compliance import RulePack, ComplianceCategory

# 创建自定义规则包
my_pack = RulePack(
    name="my-custom-rules",
    category=ComplianceCategory.SECURITY,
    description="My custom security rules",
    rules=[...],
)

market = RuleMarket()

# 上传到社区
market.upload(my_pack, author="your-name")
```

### 3. CLI 命令

```bash
# 列出可用规则包
harness market list

# 下载规则包
harness market download security-best-practices

# 安装规则包
harness market install security-best-practices

# 上传自定义规则包
harness market upload my-rules.yaml --author "your-name"

# 搜索规则包
harness market search security
```

## 规则包格式

规则包使用 YAML 格式：

```yaml
name: security-best-practices
version: 1.0.0
author: community
description: "Security best practices rules"
category: security

rules:
  - id: no-hardcoded-passwords
    severity: critical
    description: "禁止硬编码密码"
    checker: regex
    config:
      pattern: "password\\s*=\\s*['\\\"][^'\\\"]+['\\\"]"
      message: "Found hardcoded password"

  - id: require-https
    severity: high
    description: "必须使用 HTTPS"
    checker: regex
    config:
      pattern: "http://[^\\s]+"
      message: "Found HTTP URL (should use HTTPS)"
```

## 规则市场架构

```
规则市场
├── 本地规则库 (~/.harness/market/)
│   ├── available/          # 可用的规则包
│   ├── installed/          # 已安装的规则包
│   └── cache/              # 缓存
├── 远程规则库 (GitHub/自定义源)
│   ├── official/           # 官方规则包
│   └── community/          # 社区规则包
└── 规则包管理
    ├── 下载
    ├── 安装
    ├── 卸载
    └── 更新
```

## 规则源

默认规则源：
1. **官方源**: https://github.com/harness-cook/rules-official
2. **社区源**: https://github.com/harness-cook/rules-community

可以自定义规则源：

```python
market = RuleMarket()
market.add_source("my-source", "https://github.com/my-org/my-rules")
```
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

import yaml

logger = logging.getLogger("harness.rule_market")


# ═══════════════════════════════════════════════════════════
#  规则包元数据
# ═══════════════════════════════════════════════════════════

@dataclass
class RulePackMetadata:
    """规则包元数据"""
    name: str
    version: str = "1.0.0"
    author: str = "unknown"
    description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    download_count: int = 0
    rating: float = 0.0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "download_count": self.download_count,
            "rating": self.rating,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RulePackMetadata":
        """从字典创建"""
        return cls(**data)


# ═══════════════════════════════════════════════════════════
#  规则市场
# ═══════════════════════════════════════════════════════════

class RuleMarket:
    """规则市场——管理规则包的发现、下载、上传"""

    def __init__(
        self,
        market_dir: Optional[str] = None,
        sources: Optional[List[str]] = None,
    ):
        """
        初始化规则市场

        Args:
            market_dir: 本地市场目录（默认 ~/.harness/market）
            sources: 远程规则源列表
        """
        self._market_dir = Path(market_dir or os.path.expanduser("~/.harness/market"))
        self._available_dir = self._market_dir / "available"
        self._installed_dir = self._market_dir / "installed"
        self._cache_dir = self._market_dir / "cache"

        # 默认规则源
        self._sources = sources or [
            "https://github.com/harness-cook/rules-official",
            "https://github.com/harness-cook/rules-community",
        ]

        # 确保目录存在
        self._init_directories()

    def _init_directories(self) -> None:
        """初始化目录结构"""
        self._market_dir.mkdir(parents=True, exist_ok=True)
        self._available_dir.mkdir(exist_ok=True)
        self._installed_dir.mkdir(exist_ok=True)
        self._cache_dir.mkdir(exist_ok=True)

    # ─── 规则包发现 ────────────────────────────────────

    def list_available(self, category: Optional[str] = None) -> List[RulePackMetadata]:
        """
        列出可用的规则包

        Args:
            category: 按类别过滤

        Returns:
            规则包元数据列表
        """
        available = []

        # 从本地可用目录读取
        for metadata_file in self._available_dir.glob("*/metadata.json"):
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                metadata = RulePackMetadata.from_dict(data)

                if category and metadata.category != category:
                    continue

                available.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load metadata from {metadata_file}: {e}")

        return sorted(available, key=lambda m: m.download_count, reverse=True)

    def search(self, query: str) -> List[RulePackMetadata]:
        """
        搜索规则包

        Args:
            query: 搜索关键词

        Returns:
            匹配的规则包列表
        """
        query_lower = query.lower()
        results = []

        for metadata in self.list_available():
            if (
                query_lower in metadata.name.lower()
                or query_lower in metadata.description.lower()
                or any(query_lower in tag.lower() for tag in metadata.tags)
            ):
                results.append(metadata)

        return results

    # ─── 规则包下载 ────────────────────────────────────

    def download(self, pack_name: str, version: Optional[str] = None) -> bool:
        """
        下载规则包

        Args:
            pack_name: 规则包名称
            version: 版本号（默认最新版本）

        Returns:
            是否成功
        """
        logger.info(f"Downloading rule pack: {pack_name} (version: {version or 'latest'})")

        # TODO: 实现从远程源下载
        # 目前只是创建一个示例规则包
        pack_dir = self._available_dir / pack_name
        pack_dir.mkdir(exist_ok=True)

        # 创建示例元数据
        metadata = RulePackMetadata(
            name=pack_name,
            version=version or "1.0.0",
            author="community",
            description=f"Downloaded rule pack: {pack_name}",
            category="security",
            tags=["downloaded", "community"],
        )

        metadata_file = pack_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata.to_dict(), f, indent=2)

        # 创建示例规则文件
        rules_file = pack_dir / "rules.yaml"
        with open(rules_file, 'w') as f:
            yaml.dump({
                "name": pack_name,
                "version": metadata.version,
                "rules": [],
            }, f)

        logger.info(f"Downloaded rule pack to {pack_dir}")
        return True

    def install(self, pack_name: str) -> bool:
        """
        安装规则包到本地

        Args:
            pack_name: 规则包名称

        Returns:
            是否成功
        """
        available_pack = self._available_dir / pack_name
        if not available_pack.exists():
            logger.error(f"Rule pack not available: {pack_name}")
            return False

        installed_pack = self._installed_dir / pack_name

        # 如果已安装，先卸载
        if installed_pack.exists():
            self.uninstall(pack_name)

        # 复制规则包
        shutil.copytree(available_pack, installed_pack)

        logger.info(f"Installed rule pack: {pack_name}")
        return True

    def uninstall(self, pack_name: str) -> bool:
        """
        卸载已安装的规则包

        Args:
            pack_name: 规则包名称

        Returns:
            是否成功
        """
        installed_pack = self._installed_dir / pack_name
        if not installed_pack.exists():
            logger.warning(f"Rule pack not installed: {pack_name}")
            return False

        shutil.rmtree(installed_pack)
        logger.info(f"Uninstalled rule pack: {pack_name}")
        return True

    def list_installed(self) -> List[RulePackMetadata]:
        """
        列出已安装的规则包

        Returns:
            规则包元数据列表
        """
        installed = []

        for metadata_file in self._installed_dir.glob("*/metadata.json"):
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                metadata = RulePackMetadata.from_dict(data)
                installed.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load metadata from {metadata_file}: {e}")

        return installed

    # ─── 规则包上传 ────────────────────────────────────

    def upload(
        self,
        pack_name: str,
        rules_file: str,
        author: str,
        description: str = "",
        category: str = "general",
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        上传自定义规则包到市场

        Args:
            pack_name: 规则包名称
            rules_file: 规则文件路径
            author: 作者
            description: 描述
            category: 类别
            tags: 标签列表

        Returns:
            是否成功
        """
        logger.info(f"Uploading rule pack: {pack_name} by {author}")

        # 读取规则文件
        rules_path = Path(rules_file)
        if not rules_path.exists():
            logger.error(f"Rules file not found: {rules_file}")
            return False

        # 创建规则包目录
        pack_dir = self._available_dir / pack_name
        pack_dir.mkdir(exist_ok=True)

        # 复制规则文件
        shutil.copy(rules_path, pack_dir / "rules.yaml")

        # 创建元数据
        metadata = RulePackMetadata(
            name=pack_name,
            version="1.0.0",
            author=author,
            description=description,
            category=category,
            tags=tags or [],
        )

        metadata_file = pack_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata.to_dict(), f, indent=2)

        logger.info(f"Uploaded rule pack to {pack_dir}")
        return True

    # ─── 规则源管理 ────────────────────────────────────

    def add_source(self, name: str, url: str) -> None:
        """
        添加规则源

        Args:
            name: 源名称
            url: 源 URL
        """
        self._sources.append(url)
        logger.info(f"Added rule source: {name} ({url})")

    def list_sources(self) -> List[str]:
        """
        列出所有规则源

        Returns:
            规则源列表
        """
        return list(self._sources)

    def remove_source(self, url: str) -> bool:
        """
        移除规则源

        Args:
            url: 源 URL

        Returns:
            是否成功
        """
        if url in self._sources:
            self._sources.remove(url)
            logger.info(f"Removed rule source: {url}")
            return True
        return False

    # ─── 同步 ──────────────────────────────────────────

    def sync(self) -> int:
        """
        从远程源同步规则包列表

        Returns:
            同步的规则包数量
        """
        logger.info("Syncing rule market...")

        # TODO: 实现从远程源同步
        # 目前返回 0

        logger.info("Sync completed")
        return 0


# ═══════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════

_market_instance: Optional[RuleMarket] = None


def get_rule_market(market_dir: Optional[str] = None) -> RuleMarket:
    """获取规则市场实例"""
    global _market_instance
    if _market_instance is None:
        _market_instance = RuleMarket(market_dir=market_dir)
    return _market_instance
