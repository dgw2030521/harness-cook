"""
CallGraphBuilder 测试——方法级调用图构建
"""

import os
import tempfile
import pytest

from harness.call_graph import CallGraph, CallGraphBuilder


class TestCallGraphBuilderPython:

    def test_simple_function_calls(self):
        """函数间调用关系"""
        code = '''
def foo():
    bar()
    baz()

def bar():
    baz()

def baz():
    pass
'''
        builder = CallGraphBuilder()
        cg = builder.scan_python(code, "test.py")
        assert "foo" in cg.definitions
        assert "bar" in cg.definitions
        assert "baz" in cg.definitions
        # foo calls bar and baz
        assert "bar" in cg.calls.get("foo", [])
        assert "baz" in cg.calls.get("foo", [])

    def test_class_method_calls(self):
        """类方法调用"""
        code = '''
class MyClass:
    def __init__(self):
        self.setup()

    def setup(self):
        self.process()

    def process(self):
        pass
'''
        builder = CallGraphBuilder()
        cg = builder.scan_python(code, "test.py")
        assert "MyClass.__init__" in cg.definitions
        assert "MyClass.setup" in cg.definitions
        # __init__ calls self.setup → detected as "setup"
        init_callees = cg.calls.get("MyClass.__init__", [])
        assert "setup" in init_callees

    def test_empty_code(self):
        builder = CallGraphBuilder()
        cg = builder.scan_python("", "empty.py")
        assert len(cg.definitions) == 0

    def test_syntax_error_skipped(self):
        code = "def broken( { invalid }"
        builder = CallGraphBuilder()
        cg = builder.scan_python(code, "broken.py")
        assert len(cg.definitions) == 0

    def test_module_level_calls(self):
        """模块级调用(不在类中的函数)"""
        code = '''
import os

def main():
    os.path.exists("/tmp")
    helper()

def helper():
    return True
'''
        builder = CallGraphBuilder()
        cg = builder.scan_python(code, "test.py")
        assert "main" in cg.definitions
        assert "helper" in cg.definitions
        # main calls helper
        assert "helper" in cg.calls.get("main", [])