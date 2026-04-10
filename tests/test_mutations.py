"""Tests for the mutation engine and individual mutation classes."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pluckit import Plucker, PluckerError
from pluckit.mutations import (
    AddArg,
    AddParam,
    Append,
    ClearBody,
    InsertAfter,
    InsertBefore,
    Prepend,
    Remove,
    RemoveArg,
    RemoveParam,
    Rename,
    ReplaceWith,
    ScopedReplace,
    Unwrap,
    Wrap,
)


SAMPLE = textwrap.dedent("""\
    def greet(name: str) -> str:
        return f'hello {name}'


    def farewell(name: str) -> str:
        return f'goodbye {name}'


    def process_data(items):
        result = []
        for item in items:
            result.append(item * 2)
        return result


    class Config:
        def __init__(self, db):
            self.db = db

        def get_user(self, user_id):
            return self.db.fetch(user_id)
""")


@pytest.fixture
def mut_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(SAMPLE)
    return tmp_path


@pytest.fixture
def pluck(mut_repo):
    return Plucker(code=str(mut_repo / "src/*.py"))


# ---------------------------------------------------------------------------
# Unit tests for individual mutation classes
# ---------------------------------------------------------------------------

class TestReplaceWith:
    def test_replaces_entire_node(self):
        m = ReplaceWith("def replaced():\n    pass")
        node = {"type": "function_definition"}
        result = m.compute(node, "def old():\n    return 1\n", "")
        assert "replaced" in result
        assert "old" not in result

    def test_preserves_indentation(self):
        m = ReplaceWith("def bar():\n    return 2")
        node = {"type": "function_definition"}
        # Method indented 4 spaces inside a class
        result = m.compute(node, "    def foo():\n        return 1\n", "")
        assert result.startswith("    def bar():")


class TestScopedReplace:
    def test_string_replace_within_node(self):
        m = ScopedReplace("return None", "raise ValueError('invalid')")
        node = {}
        result = m.compute(node, "def foo():\n    return None\n", "")
        assert "raise ValueError" in result
        assert "return None" not in result

    def test_leaves_non_matching_text(self):
        m = ScopedReplace("foo", "bar")
        node = {}
        result = m.compute(node, "def baz():\n    return 1\n", "")
        assert result == "def baz():\n    return 1\n"


class TestPrepend:
    def test_inserts_after_signature(self):
        m = Prepend("print('hi')")
        node = {}
        result = m.compute(node, "def greet(name):\n    return f'hello {name}'\n", "")
        lines = result.split("\n")
        assert lines[0] == "def greet(name):"
        assert "print('hi')" in lines[1]
        assert lines[2].strip().startswith("return")

    def test_matches_body_indentation(self):
        m = Prepend("print('hi')")
        node = {}
        result = m.compute(node, "def foo():\n    return 1\n", "")
        # Inserted line should be indented to match "    return 1"
        assert "    print('hi')" in result


class TestAppend:
    def test_adds_to_end_of_body(self):
        m = Append("print('done')")
        node = {}
        result = m.compute(node, "def foo():\n    return 1", "")
        lines = result.rstrip("\n").split("\n")
        assert "print('done')" in lines[-1]
        assert "    print('done')" in result


class TestWrap:
    def test_wraps_with_indentation(self):
        m = Wrap("try:", "except Exception:\n    pass")
        node = {}
        result = m.compute(node, "def foo():\n    return 1\n", "")
        assert "try:" in result
        assert "except Exception:" in result


class TestRemove:
    def test_returns_empty(self):
        m = Remove()
        assert m.compute({}, "def foo():\n    pass\n", "") == ""


class TestRename:
    def test_replaces_first_name_occurrence(self):
        m = Rename("new_name")
        node = {"name": "old_name"}
        result = m.compute(node, "def old_name():\n    return old_name\n", "")
        # Only the definition (first occurrence) should be renamed
        assert result == "def new_name():\n    return old_name\n"


class TestAddParam:
    def test_inserts_in_empty_params(self):
        m = AddParam("x: int")
        result = m.compute({}, "def foo():\n    return 1\n", "")
        assert "def foo(x: int):" in result

    def test_appends_to_existing_params(self):
        m = AddParam("timeout: int = 30")
        result = m.compute({}, "def foo(a, b):\n    return a + b\n", "")
        assert "def foo(a, b, timeout: int = 30):" in result

    def test_ignores_nested_parens_in_body(self):
        m = AddParam("x: int")
        result = m.compute({}, "def foo(a):\n    return call(1, 2)\n", "")
        # Only the signature paren should be modified
        assert "def foo(a, x: int):" in result
        assert "return call(1, 2)" in result


class TestRemoveParam:
    def test_removes_single_param(self):
        m = RemoveParam("b")
        result = m.compute({}, "def foo(a, b, c):\n    return 1\n", "")
        assert "def foo(a, c):" in result

    def test_removes_with_type_annotation(self):
        m = RemoveParam("timeout")
        result = m.compute({}, "def foo(a, timeout: int = 30):\n    return 1\n", "")
        assert "def foo(a):" in result

    def test_removes_last_param(self):
        m = RemoveParam("b")
        result = m.compute({}, "def foo(a, b):\n    return 1\n", "")
        assert "def foo(a):" in result


class TestAddArg:
    def test_inserts_in_empty_call(self):
        m = AddArg("timeout=30")
        result = m.compute({}, "foo()\n", "")
        assert result == "foo(timeout=30)\n"

    def test_appends_to_existing_args(self):
        m = AddArg("timeout=timeout")
        result = m.compute({}, "foo(a, b)\n", "")
        assert "foo(a, b, timeout=timeout)" in result

    def test_positional_expression(self):
        m = AddArg("42")
        result = m.compute({}, "foo()\n", "")
        assert "foo(42)" in result


class TestRemoveArg:
    def test_removes_keyword_arg_middle(self):
        m = RemoveArg("b")
        result = m.compute({}, "foo(a, b=2, c=3)\n", "")
        assert "foo(a, c=3)" in result

    def test_removes_trailing_keyword_arg(self):
        m = RemoveArg("timeout")
        result = m.compute({}, "foo(url, timeout=30)\n", "")
        assert "foo(url)" in result

    def test_removes_leading_arg(self):
        m = RemoveArg("a")
        result = m.compute({}, "foo(a, b)\n", "")
        assert "foo(b)" in result


# ---------------------------------------------------------------------------
# End-to-end mutation tests via Plucker
# ---------------------------------------------------------------------------

class TestEndToEndReplace:
    def test_scoped_replace(self, pluck, mut_repo):
        pluck.find(".fn#greet").replaceWith("f'hello {name}'", "f'hi {name}'")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "f'hi {name}'" in content
        # Other functions unchanged
        assert "f'goodbye {name}'" in content

    def test_full_replace(self, pluck, mut_repo):
        pluck.find(".fn#greet").replaceWith(
            "def greet(name: str) -> str:\n    return f'bonjour {name}'"
        )
        content = (mut_repo / "src" / "app.py").read_text()
        assert "bonjour" in content
        assert "farewell" in content  # untouched


class TestEndToEndInsertions:
    def test_prepend(self, pluck, mut_repo):
        pluck.find(".fn#greet").prepend("print('entering')")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "print('entering')" in content
        # Original body preserved
        assert "hello" in content

    def test_append(self, pluck, mut_repo):
        pluck.find(".fn#greet").append("print('leaving')")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "print('leaving')" in content


class TestEndToEndRemoval:
    def test_remove_function(self, pluck, mut_repo):
        pluck.find(".fn#greet").remove()
        content = (mut_repo / "src" / "app.py").read_text()
        assert "def greet" not in content
        assert "def farewell" in content


class TestEndToEndRename:
    def test_rename_function(self, pluck, mut_repo):
        pluck.find(".fn#greet").rename("salute")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "def salute" in content
        # The function that was called "greet" no longer exists with that name
        assert "def greet" not in content


class TestEndToEndAddParam:
    def test_add_param_to_function(self, pluck, mut_repo):
        pluck.find(".fn#greet").addParam("timeout: int = 30")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "def greet(name: str, timeout: int = 30)" in content


class TestEndToEndRemoveParam:
    def test_remove_param(self, pluck, mut_repo):
        pluck.find(".fn#process_data").removeParam("items")
        content = (mut_repo / "src" / "app.py").read_text()
        assert "def process_data():" in content or "def process_data ():" in content


class TestEndToEndAddArg:
    def test_add_arg_to_call(self, pluck, mut_repo):
        # Create a fresh file with a clear call site
        (mut_repo / "src" / "caller.py").write_text(
            "def caller():\n    return greet('world')\n"
        )
        pluck2 = Plucker(code=str(mut_repo / "src/caller.py"))
        pluck2.find(".call#greet").addArg("timeout=30")
        content = (mut_repo / "src" / "caller.py").read_text()
        assert "greet('world', timeout=30)" in content


class TestEndToEndRemoveArg:
    def test_remove_keyword_arg(self, pluck, mut_repo):
        (mut_repo / "src" / "caller.py").write_text(
            "def caller():\n    return fetch(url='x', timeout=30)\n"
        )
        pluck2 = Plucker(code=str(mut_repo / "src/caller.py"))
        pluck2.find(".call#fetch").removeArg("timeout")
        content = (mut_repo / "src" / "caller.py").read_text()
        assert "fetch(url='x')" in content
        assert "timeout=30" not in content


class TestClearBody:
    def test_python_function(self):
        m = ClearBody()
        text = "def foo(x):\n    y = x * 2\n    return y\n"
        result = m.compute({"language": "python"}, text, "")
        assert "def foo(x):" in result
        assert "pass" in result
        assert "return y" not in result

    def test_cpp_function_preserves_closing_brace(self):
        m = ClearBody()
        text = "int get_timeout() const {\n    return timeout;\n}"
        result = m.compute({"language": "cpp"}, text, "")
        assert "int get_timeout() const {" in result
        assert "}" in result
        assert "return timeout" not in result

    def test_java_method(self):
        m = ClearBody()
        text = "public int foo() {\n    return 1;\n}"
        result = m.compute({"language": "java"}, text, "")
        assert "public int foo() {" in result
        assert "}" in result
        assert "return 1" not in result


class TestInsertBeforeAfter:
    """End-to-end tests for InsertBefore/InsertAfter with real AST anchor resolution."""

    def test_insert_before_method_in_class(self, mut_repo):
        import textwrap
        (mut_repo / "src" / "classes.py").write_text(textwrap.dedent("""\
            class Foo:
                def __init__(self, x):
                    self.x = x

                def bar(self):
                    return self.x
        """))
        pluck = Plucker(code=str(mut_repo / "src/classes.py"))
        pluck.find(".cls#Foo").insertBefore(".fn#bar", "def pre_bar(self):\n    pass")
        content = (mut_repo / "src" / "classes.py").read_text()
        # pre_bar should appear before bar
        pre_idx = content.find("def pre_bar")
        bar_idx = content.find("def bar")
        assert pre_idx != -1
        assert pre_idx < bar_idx

    def test_insert_after_method_in_class(self, mut_repo):
        import textwrap
        (mut_repo / "src" / "classes.py").write_text(textwrap.dedent("""\
            class Foo:
                def bar(self):
                    return 1

                def baz(self):
                    return 2
        """))
        pluck = Plucker(code=str(mut_repo / "src/classes.py"))
        pluck.find(".cls#Foo").insertAfter(".fn#bar", "def post_bar(self):\n    pass")
        content = (mut_repo / "src" / "classes.py").read_text()
        bar_idx = content.find("def bar")
        post_idx = content.find("def post_bar")
        baz_idx = content.find("def baz")
        assert bar_idx < post_idx < baz_idx

    def test_insert_before_missing_anchor_is_noop(self, mut_repo):
        import textwrap
        (mut_repo / "src" / "empty.py").write_text(textwrap.dedent("""\
            class Foo:
                def bar(self):
                    return 1
        """))
        original = (mut_repo / "src" / "empty.py").read_text()
        pluck = Plucker(code=str(mut_repo / "src/empty.py"))
        pluck.find(".cls#Foo").insertBefore(".fn#does_not_exist", "def extra(self): pass")
        content = (mut_repo / "src" / "empty.py").read_text()
        assert content == original


class TestTransactionRollback:
    def test_rollback_on_syntax_error(self, pluck, mut_repo):
        original = (mut_repo / "src" / "app.py").read_text()
        with pytest.raises(PluckerError, match="invalid syntax"):
            pluck.find(".fn#greet").replaceWith("def greet(:::\n    broken {{{{ syntax")
        content = (mut_repo / "src" / "app.py").read_text()
        assert content == original

    def test_multi_node_transaction(self, pluck, mut_repo):
        """When mutating multiple nodes in one file, all should succeed or all revert."""
        original = (mut_repo / "src" / "app.py").read_text()
        # This should succeed — rename every function in one call
        pluck.find(".fn").replaceWith("return", "return  # modified")
        content = (mut_repo / "src" / "app.py").read_text()
        assert content != original
        assert "# modified" in content


class TestEmptySelection:
    def test_empty_mutation_is_noop(self, pluck, mut_repo):
        original = (mut_repo / "src" / "app.py").read_text()
        pluck.find(".fn#nonexistent").replaceWith("whatever")
        content = (mut_repo / "src" / "app.py").read_text()
        assert content == original
