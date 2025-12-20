"""Tests for the sqlitey module.

This module tests the core functionality of sqlitey including:
- Sql class (raw and template queries)
- Db class (execute, fetch, commit operations)
- Row factories (dict and namedtuple)
- Security features (cursor protection, path traversal prevention)
"""

import sqlite3
from pathlib import Path
from sqlite3.dbapi2 import OperationalError
from tempfile import NamedTemporaryFile

from pytest import fixture, raises

from sqlitey import Db, DbPathConfig, Sql, dict_factory, namedtuple_factory


@fixture
def temp_db_path():
    """Create a temporary SQLite database with test data.

    Yields a path to a database containing a 'users' table with two rows:
    - (1, 'Alice')
    - (2, 'John')
    """
    with NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        db_path = Path(tmp.name)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'John')")
        conn.commit()
        conn.close()
        yield db_path


@fixture
def config(temp_db_path):
    """Create a DbPathConfig with the temp database and test SQL templates."""
    return DbPathConfig(
        database=temp_db_path,
        sql_templates_dir=Path(__file__).resolve().parent / "sql"
    )


def test_raw_sql():
    """Test loading raw SQL."""
    sql = Sql.raw("SELECT 1")
    assert sql.load_query() == "SELECT 1"


def test_template_sql_no_path_config():
    """Test loading a template without a path."""
    sql = Sql.template("test.sql")
    with raises(ValueError, match="No template path configured"):
        sql.load_query()


def test_template_sql():
    """Test loading a template."""
    sql = Sql.template("test.sql", path=Path(__file__).resolve().parent / "sql")
    assert sql.load_query() == "SELECT 1;"


def test_db_fetchone(config):
    """Test using fetchone."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?")
    with Db.from_config(config) as db:
        result = db.fetchone(sql, (1,))
    assert result == (1, "Alice")


def test_db_fetchone_dict_factory(config):
    """Test using fetchone and the dict factory."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?")
    with Db.from_config(config, row_factory=dict_factory) as db:
        result = db.fetchone(sql, (1,))
    assert result == {"id": 1, "name": "Alice"}


def test_db_fetchone_namedtuple_factory(config):
    """Test using fetchone and the namedtuple factory."""
    sql = Sql.raw("SELECT id, name FROM users WHERE id = ?")
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        result = db.fetchone(sql, (1,))
    assert result.id == 1
    assert result.name == "Alice"


def test_db_fetchall(config):
    """Test using fetchall."""
    sql = Sql.raw("SELECT id, name FROM users")
    with Db.from_config(config) as db:
        results = db.fetchall(sql)
    assert results == [(1, "Alice"), (2, "John")]


def test_db_fetchall_dict_factory(config):
    """Test using fetchall and the dict factory."""
    sql = Sql.raw("SELECT id, name FROM users")
    with Db.from_config(config, row_factory=dict_factory) as db:
        results = db.fetchall(sql)
    assert results == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "John"}]


def test_db_fetchall_namedtuple_factory(config):
    """Test using fetchall and the namedtuple factory."""
    sql = Sql.raw("SELECT id, name FROM users")
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        results = db.fetchall(sql)
    assert results[0].id == 1
    assert results[0].name == "Alice"
    assert results[1].id == 2
    assert results[1].name == "John"


def test_db_commit(config):
    """Test using commit."""
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        db.commit(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
        result = db.fetchone(Sql.raw("SELECT COUNT(id) as total FROM users"))
    assert result.total == 3


def test_db_context_manager_rollback(config):
    """Test rolling back in context manager."""
    with raises(OperationalError):
        with Db.from_config(config) as db:
            db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
            db.execute(Sql.raw("SYNTAX ERROR;"))  # raise
    with Db.from_config(config) as db:
        result = db.fetchone(Sql.raw("SELECT id FROM users WHERE id = 3"))
    assert result is None


def test_access_cursor_execute(config):
    """Test accessing cursor.execute() is forbidden."""
    with Db.from_config(config) as db:
        with raises(AttributeError, match="Cannot access execute from cursor directly"):
            db._cursor.execute(Sql.raw("SELECT 1;"))
        # however we should be able to access other attributes
        assert db._cursor.rowcount == -1


def test_db_autocommit_behaviour(config):
    """Test autocommit works as expected in context manager."""
    with raises(OperationalError):
        with Db.from_config(config, autocommit=True) as db:
            db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
            db.execute(Sql.raw("SYNTAX ERROR"))  # raise
    with Db.from_config(config) as db:
        result = db.fetchone(Sql.raw("SELECT id FROM users WHERE id = 3"))
    assert result == (3,)


def test_db_undefer_template_path(temp_db_path):
    """Test setting template path not using a config."""
    sql = Sql.template("test.sql", path=Path(__file__).resolve().parent / "sql")
    with Db(temp_db_path) as db:
        result = db.fetchone(sql)
    assert result == (1,)


def test_db_defer_template_path(config):
    """Test setting template path from a config."""
    with Db.from_config(config) as db:
        result = db.fetchone(Sql.template("test.sql"))
    assert result == (1,)


def test_executescript(config):
    """Test using executescript."""
    with Db.from_config(config) as db:
        db.executescript(
            Sql.raw(
                "INSERT INTO users VALUES (3, 'Kate');"
                "INSERT INTO users VALUES (4, 'Johny');"
            )
        )
        result = db.fetchone(Sql.raw("SELECT COUNT(id) as total FROM users"))
    assert result == (4,)


def test_executemany(config):
    """Test using executemany."""
    updates = [
        ('Alicia', 1),
        ('Bobby', 2),
    ]
    with Db.from_config(config, autocommit=True) as db:
        db.executemany(Sql.raw("UPDATE users SET name = ? WHERE id = ?"), updates)
        results = db.fetchall(Sql.raw("SELECT name FROM users"))
    assert "Alicia" in str(results)
    assert "Bobby" in str(results)


def test_template_path_traversal_dotdot():
    """Test path traversal with .. is blocked."""
    sql = Sql.template("../etc/passwd", path=Path(__file__).resolve().parent / "sql")
    with raises(ValueError, match="Invalid template filename"):
        sql.load_query()


def test_template_path_traversal_absolute():
    """Test path traversal with absolute path is blocked."""
    sql = Sql.template("/etc/passwd", path=Path(__file__).resolve().parent / "sql")
    with raises(ValueError, match="Invalid template filename"):
        sql.load_query()


def test_template_file_not_found():
    """Test loading a template that doesn't exist."""
    sql = Sql.template("nonexistent.sql", path=Path(__file__).resolve().parent / "sql")
    with raises(FileNotFoundError, match="SQL template not found"):
        sql.load_query()


def test_access_cursor_executemany(config):
    """Test accessing cursor.executemany() is forbidden."""
    with Db.from_config(config) as db:
        with raises(AttributeError, match="Cannot access executemany from cursor directly"):
            db._cursor.executemany(Sql.raw("SELECT 1;"), [])


def test_access_cursor_executescript(config):
    """Test accessing cursor.executescript() is forbidden."""
    with Db.from_config(config) as db:
        with raises(AttributeError, match="Cannot access executescript from cursor directly"):
            db._cursor.executescript(Sql.raw("SELECT 1;"))
