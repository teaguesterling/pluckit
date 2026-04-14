import textwrap

import duckdb
import pytest

from pluckit.plucker import Plucker
from pluckit.pluckins.base import Pluckin
from pluckit.types import PluckerError


@pytest.fixture
def proj_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def hello(name: str) -> str:
            return f"hello {name}"

        def goodbye(name: str) -> str:
            return f"goodbye {name}"
    """))
    return tmp_path


class TestPluckerCreation:
    def test_create_with_code_glob(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        assert pluck is not None

    def test_create_without_code(self):
        pluck = Plucker()
        assert pluck is not None

    def test_create_with_repo(self, proj_dir):
        pluck = Plucker(code="src/**/*.py", repo=str(proj_dir))
        assert pluck.find(".function").count() >= 2

    def test_create_with_existing_db(self, proj_dir):
        conn = duckdb.connect()
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"), db=conn)
        assert pluck.find(".function").count() >= 2


class TestSourceResolution:
    def test_glob_source(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        assert pluck.find(".function").count() >= 2

    def test_single_file_source(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/app.py"))
        assert pluck.find(".function").count() >= 2

    def test_table_source(self, proj_dir):
        conn = duckdb.connect()
        conn.sql("INSTALL sitting_duck FROM community")
        conn.sql("LOAD sitting_duck")
        conn.sql(f"CREATE TABLE my_index AS SELECT * FROM read_ast('{proj_dir}/src/**/*.py')")
        pluck = Plucker(code="my_index", db=conn)
        assert pluck.find(".function").count() >= 2

    def test_no_source_find_raises(self):
        pluck = Plucker()
        with pytest.raises(PluckerError, match="No source configured"):
            pluck.find(".function")


class TestSourceMethod:
    def test_source_works_without_default(self, proj_dir):
        pluck = Plucker()
        sel = pluck.source(str(proj_dir / "src/app.py")).find(".function")
        assert sel.count() >= 2

    def test_source_with_default(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        sel = pluck.source(str(proj_dir / "src/app.py")).find(".function")
        assert sel.count() >= 2


class TestPluginWiring:
    def test_plugin_methods_available(self, proj_dir):
        class Dummy(Pluckin):
            name = "dummy"
            methods = {"ping": "_ping"}
            def _ping(self, sel):
                return "pong"

        pluck = Plucker(code=str(proj_dir / "src/**/*.py"), plugins=[Dummy])
        sel = pluck.find(".function")
        assert sel.ping() == "pong"

    def test_plugin_not_loaded_raises(self, proj_dir):
        pluck = Plucker(code=str(proj_dir / "src/**/*.py"))
        sel = pluck.find(".function")
        with pytest.raises(PluckerError, match="Calls"):
            sel.callers()
