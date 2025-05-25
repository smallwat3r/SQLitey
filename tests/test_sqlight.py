import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile

from pytest import fixture, raises

from sqlight import Db, DbConfig, Sql, dict_factory, namedtuple_factory


@fixture
def temp_db_path():
    with NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        db_path = Path(tmp.name)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'John');")
        conn.commit()
        conn.close()
        yield db_path


@fixture
def config(temp_db_path):
    return DbConfig(
        database=temp_db_path,
        sql_templates_dir=Path(__file__).resolve().parent / "sql"
    )


def test_sql_direct_instantiation():
    """Test using Sql without a classmethod."""
    with raises(TypeError, match="Direct instantiation is not allowed"):
        Sql(...)


def test_raw_sql():
    """Test loading raw SQL."""
    sql = Sql.raw("SELECT 1;")
    assert sql.query == "SELECT 1;"


def test_template_sql_no_path_config():
    """Test loading a template without a path."""
    sql = Sql.template("test.sql")
    with raises(ValueError, match="No path config supplied"):
        sql.query


def test_template_sql():
    """Test loading a template."""
    sql = Sql.template("test.sql")
    sql.path = Path(__file__).resolve().parent / "sql"
    assert sql.query == "SELECT 1;"


def test_db_fetchone(config):
    """Test using fetchone."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?;")
    with Db.from_config(config) as db:
        result = db.fetchone(sql, (1,))
    assert result == (1, "Alice")


def test_db_fetchone_dict_factory(config):
    """Test using fetchone and the dict factory."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?;")
    with Db.from_config(config, row_factory=dict_factory) as db:
        result = db.fetchone(sql, (1,))
    assert result == {"id": 1, "name": "Alice"}


def test_db_fetchone_namedtuple_factory(config):
    """Test using fetchone and the namedtuple factory."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?;")
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        result = db.fetchone(sql, (1,))
    assert result.id == 1
    assert result.name == "Alice"


def test_db_fetchall(config):
    """Test using fetchall."""
    sql = Sql.raw("SELECT id, name FROM users;")
    with Db.from_config(config) as db:
        results = db.fetchall(sql)
    assert results == [(1, "Alice"), (2, "John")]


def test_db_fetchall_dict_factory(config):
    """Test using fetchall and the dict factory."""
    sql = Sql.raw("SELECT id, name FROM users;")
    with Db.from_config(config, row_factory=dict_factory) as db:
        results = db.fetchall(sql)
    assert results == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "John"}]


def test_db_fetchall_namedtuple_factory(config):
    """Test using fetchall and the namedtuple factory."""
    sql = Sql.raw("SELECT id, name FROM users;")
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        results = db.fetchall(sql)
    assert results[0].id == 1
    assert results[0].name == "Alice"
    assert results[1].id == 2
    assert results[1].name == "John"


def test_db_commit(config):
    """Test using commit."""
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        db.commit(Sql.raw("INSERT INTO users VALUES (3, 'Kate');"))
        result = db.fetchone(Sql.raw("SELECT COUNT(id) as total FROM users;"))
    assert result.total == 3


def test_db_undefer_template_path(temp_db_path):
    """Test setting template path not using a config."""
    sql = Sql.template("test.sql", path=Path(__file__).resolve().parent / "sql")
    with Db(temp_db_path) as db:
        result = db.fetchone(sql)
    assert result == (1,)
