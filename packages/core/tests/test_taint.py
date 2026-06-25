"""
污点追踪测试——TaintTracker source→Sink 数据流检测
"""

import pytest

from harness.taint import (
    TaintTracker,
    TaintSource,
    TaintSink,
    TaintSourceType,
    TaintSinkType,
    TaintFinding,
    BUILTIN_SOURCES,
    BUILTIN_SINKS,
)


# ─── Source 识别 ────────────────────────────────────────

class TestSourceIdentification:

    def test_input_function_is_source(self):
        """input() → eval() 是经典污点流"""
        code = '''
x = input("Enter name:")
eval(x)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert any(f.source_type == TaintSourceType.USER_INPUT for f in findings)
        assert any(f.sink_type == TaintSinkType.EVAL for f in findings)

    def test_os_environ_is_source(self):
        """os.environ.get 返回值是 tainted"""
        code = '''
import os
env_val = os.environ.get("SECRET_KEY")
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code, "test.py")
        # 即使没有 sink 也不会有 finding, 但 env_val 变量应被标记为 tainted
        # 验证通过后续 sink 检测
        code_with_sink = '''
import os
env_val = os.environ.get("SECRET_KEY")
eval(env_val)
'''
        findings2 = tracker.track_python(code_with_sink)
        assert len(findings2) >= 1

    def test_sys_argv_is_source(self):
        code = '''
import sys
arg = sys.argv[1]
'''
        tracker = TaintTracker()
        # argv is tainted, 但没有 sink → 无 findings
        code_clean = '''
import sys
arg = sys.argv[1]
'''
        findings_clean = tracker.track_python(code_clean)
        assert len(findings_clean) == 0


# ─── Sink 检测 ────────────────────────────────────────

class TestSinkDetection:

    def test_eval_sink_with_tainted_input(self):
        """input() → eval() 是经典污点流"""
        code = '''
x = input("Enter:")
eval(x)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) >= 1
        assert findings[0].sink_type == TaintSinkType.EVAL
        assert findings[0].source_type == TaintSourceType.USER_INPUT

    def test_os_system_sink(self):
        """os.environ → os.system 是命令注入"""
        code = '''
import os
cmd = os.environ.get("CMD")
os.system(cmd)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) >= 1
        assert findings[0].sink_type in (TaintSinkType.OS_SYSTEM, TaintSinkType.SUBPROCESS)

    def test_subprocess_sink(self):
        code = '''
import subprocess
user_input = input("cmd:")
subprocess.call(user_input, shell=True)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) >= 1
        assert findings[0].sink_type == TaintSinkType.SUBPROCESS

    def test_sql_injection_sink(self):
        """f-string SQL 是注入风险"""
        code = '''
import sqlite3
user_id = input("Enter user ID:")
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        # SQL sink 应被检测
        sql_findings = [f for f in findings if f.sink_type == TaintSinkType.SQL]
        assert len(sql_findings) >= 1


# ─── 传播 ──────────────────────────────────────────────

class TestPropagation:

    def test_simple_assignment_propagation(self):
        """y = x → y 也是 tainted"""
        code = '''
x = input("Enter:")
y = x
eval(y)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) >= 1
        # y 通过传播被标记为 tainted
        assert "y" in findings[0].source_var or "x" in findings[0].source_var

    def test_chained_propagation(self):
        """z = y = x → z 也是 tainted"""
        code = '''
x = input("data:")
y = x + " suffix"
z = y
eval(z)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) >= 1

    def test_no_propagation_without_source(self):
        """无 tainted source → 即使流入 sink 也不报警"""
        code = '''
x = "safe_constant"
eval(x)
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) == 0  # x 不是 tainted


# ─── 边界情况 ──────────────────────────────────────────

class TestEdgeCases:

    def test_syntax_error_skipped(self):
        """语法错误的代码不产生 findings"""
        code = "def broken( { invalid }"
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) == 0

    def test_no_source_no_sink(self):
        """无 source 无 sink 的代码不产生 findings"""
        code = '''
x = "hello"
y = x.upper()
'''
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) == 0

    def test_empty_code(self):
        code = ""
        tracker = TaintTracker()
        findings = tracker.track_python(code)
        assert len(findings) == 0

    def test_custom_sources_and_sinks(self):
        """自定义 source/sink 配置"""
        custom_source = TaintSource(
            TaintSourceType.USER_INPUT, r"my_custom_input",
            "Custom input source",
        )
        custom_sink = TaintSink(
            TaintSinkType.EVAL, r"my_custom_eval",
            "Custom eval sink",
        )
        tracker = TaintTracker(sources=[custom_source], sinks=[custom_sink])
        code = '''
x = my_custom_input("test")
my_custom_eval(x)
'''
        findings = tracker.track_python(code)
        assert len(findings) >= 1