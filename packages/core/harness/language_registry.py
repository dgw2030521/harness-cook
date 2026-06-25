"""
harness-cook 合规规则引擎 — 多语言支持注册表

LanguageRegistry 让任何语言只需注册 tree-sitter grammar 就能接入架构检查。

注册项包含：
- tree-sitter Language 对象（用于 AST 解析）
- 文件扩展名映射
- import 解析模式（Python 用正则，JS/TS/Java/Go 用 tree-sitter）

机制：
- 先注册所有内置语言（Python 用 stdlib ast，其他用 tree-sitter）
- tree-sitter 不可用时自动降级为正则 fallback
- 新增语言只需一行 register 调用
"""

import logging
from typing import Optional, Any


logger = logging.getLogger("harness.compliance")


# ═══════════════════════════════════════════════════════════
#  LanguageRegistry — 多语言支持注册表
# ═══════════════════════════════════════════════════════════

class LanguageRegistry:
    """语言注册表——让任何语言只需注册 tree-sitter grammar 就能接入架构检查

    注册项包含：
    - tree-sitter Language 对象（用于 AST 解析）
    - 文件扩展名映射
    - import 解析模式（Python 用正则，JS/TS/Java/Go 用 tree-sitter）

    机制：
    - 先注册所有内置语言（Python 用 stdlib ast，其他用 tree-sitter）
    - tree-sitter 不可用时自动降级为正则 fallback
    - 新增语言只需一行 register 调用
    """

    _languages: dict[str, dict] = {}

    @classmethod
    def register(cls, name: str, extensions: list[str],
                 tree_sitter_module: str = None,
                 import_pattern: str = None) -> None:
        """注册一种语言

        Args:
            name: 语言名称（如 "python", "java", "go"）
            extensions: 文件扩展名（如 [".py", ".pyw"]）
            tree_sitter_module: tree-sitter 语言模块名（如 "tree_sitter_java"）
            import_pattern: 正则 import 模式（用于 fallback，如 r'^import ...'）
        """
        cls._languages[name] = {
            "extensions": extensions,
            "tree_sitter_module": tree_sitter_module,
            "import_pattern": import_pattern,
        }

    @classmethod
    def get(cls, name: str) -> Optional[dict]:
        """获取语言配置"""
        return cls._languages.get(name)

    @classmethod
    def get_by_extension(cls, path: str) -> Optional[tuple[str, dict]]:
        """根据文件路径推断语言"""
        lower = path.lower()
        for name, config in cls._languages.items():
            for ext in config["extensions"]:
                if lower.endswith(ext):
                    return name, config
        return None

    @classmethod
    def get_tree_sitter_language(cls, name: str) -> Optional[Any]:
        """获取 tree-sitter Language 对象（动态导入）"""
        config = cls._languages.get(name)
        if not config or not config.get("tree_sitter_module"):
            return None
        try:
            module = __import__(config["tree_sitter_module"])
            from tree_sitter import Language
            # tree-sitter 语言模块提供 language() 函数返回 Language 对象
            lang_func = getattr(module, "language", None)
            if lang_func and callable(lang_func):
                return Language(lang_func())
            # TypeScript 模块特殊处理：language_typescript() / language_tsx()
            if name == "typescript":
                lang_func = getattr(module, "language_typescript", None)
                if lang_func and callable(lang_func):
                    return Language(lang_func())
        except (ImportError, Exception) as e:
            logger.debug(f"tree-sitter language for {name} not available: {e}")
            return None

    @classmethod
    def default(cls) -> None:
        """注册所有内置语言"""
        # Python（用 stdlib ast，不依赖 tree-sitter）
        cls.register("python", [".py", ".pyw"],
                      import_pattern=r'^(?:import\s+([a-zA-Z0-9_.]+)|from\s+([a-zA-Z0-9_.]+)\s+import)')

        # JavaScript / TypeScript / Vue
        cls.register("javascript", [".js", ".jsx", ".mjs"],
                      tree_sitter_module="tree_sitter_javascript")
        cls.register("typescript", [".ts", ".tsx"],
                      tree_sitter_module="tree_sitter_typescript")
        cls.register("vue", [".vue"],
                      tree_sitter_module="tree_sitter_javascript")  # Vue SFC 的 script 部分用 JS parser

        # Java
        cls.register("java", [".java"],
                      tree_sitter_module="tree_sitter_java",
                      import_pattern=r'^import\s+([a-zA-Z0-9_.]+)\s*;')

        # Go
        cls.register("go", [".go"],
                      tree_sitter_module="tree_sitter_go",
                      import_pattern=r'^import\s+["`]([^"`]+)["`]')

        # Rust
        cls.register("rust", [".rs"],
                      tree_sitter_module="tree_sitter_rust")

        # Ruby
        cls.register("ruby", [".rb"],
                      tree_sitter_module="tree_sitter_ruby")

        # C / C++
        cls.register("c", [".c", ".h"],
                      tree_sitter_module="tree_sitter_c")
        cls.register("cpp", [".cpp", ".hpp", ".cc", ".cxx"],
                      tree_sitter_module="tree_sitter_cpp")

        # Kotlin
        cls.register("kotlin", [".kt", ".kts"],
                      tree_sitter_module="tree_sitter_kotlin")

        # ─── 09号竞品报告新增语言覆盖 ───

 # Swift (Apple 生态)
        cls.register("swift", [".swift"],
                      tree_sitter_module="tree_sitter_swift",
                      import_pattern=r'^import\s+([a-zA-Z0-9_.]+)')

        # Dart (Flutter 生态)
        cls.register("dart", [".dart"],
                      tree_sitter_module="tree_sitter_dart",
                      import_pattern=r'^import\s+([a-zA-Z0-9_.]+)')

        # PHP (Web 服务端)
        cls.register("php", [".php"],
                      tree_sitter_module="tree_sitter_php",
                      import_pattern=r'^(?:require|include)(_once)?\s+[\'"]([^\'"]]+)[\'"]]')

        # Scala (大数据/JVM 生态)
        cls.register("scala", [".scala"],
                      tree_sitter_module="tree_sitter_scala",
                      import_pattern=r'^import\s+([a-zA-Z0-9_.]+)')

        # Lua (游戏/嵌入式脚本)
        cls.register("lua", [".lua"],
                      tree_sitter_module="tree_sitter_lua",
                      import_pattern=r'^require\s+[\'"]([^\'"]]+)[\'"]]')

        # Apex (Salesforce 平台)
        cls.register("apex", [".apex", ".cls"],
                      tree_sitter_module="tree_sitter_apex",
                      import_pattern=r'^\\s*\\b(from\\b)?\\s+([a-zA-Z0-9_.]+)')

    @classmethod
    def all_supported_extensions(cls) -> set[str]:
        """返回所有支持的文件扩展名"""
        exts = set()
        for name, config in cls._languages.items():
            exts.update(config["extensions"])
        return exts
