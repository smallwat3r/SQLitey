"""Tests for the sqlitey module.

This module tests the core functionality of sqlitey including:
- Sql class (raw and template queries)
- Db class (execute, fetch, commit operations)
- Row factories (dict and namedtuple)
- Transactions, template resolution and path traversal prevention
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from sqlite3.dbapi2 import OperationalError
from tempfile import NamedTemporaryFile

from pytest import fixture, raises

from sqlitey import (
    RECOMMENDED_PRAGMAS,
    Db,
    DbPathConfig,
    Sql,
    dataclass_factory,
    dict_factory,
    namedtuple_factory,
)


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
        database=temp_db_path, sql_templates_dir=Path(__file__).resolve().parent / "sql"
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
        ("Alicia", 1),
        ("Bobby", 2),
    ]
    with Db.from_config(config, autocommit=True) as db:
        db.executemany(Sql.raw("UPDATE users SET name = ? WHERE id = ?"), updates)
        results = db.fetchall(Sql.raw("SELECT name FROM users"))
    assert "Alicia" in str(results)
    assert "Bobby" in str(results)


def test_template_path_traversal_dotdot():
    """Test path traversal with .. is blocked."""
    sql = Sql.template("../etc/passwd", path=Path(__file__).resolve().parent / "sql")
    with raises(ValueError, match="Template path traversal detected"):
        sql.load_query()


def test_template_path_traversal_absolute():
    """Test path traversal with absolute path is blocked."""
    sql = Sql.template("/etc/passwd", path=Path(__file__).resolve().parent / "sql")
    with raises(ValueError, match="Template path traversal detected"):
        sql.load_query()


def test_template_file_not_found():
    """Test loading a template that doesn't exist."""
    sql = Sql.template("nonexistent.sql", path=Path(__file__).resolve().parent / "sql")
    with raises(FileNotFoundError, match="SQL template not found"):
        sql.load_query()


def test_nested_query_while_iterating(config):
    """Test running a query while iterating over another one."""
    seen = []
    with Db.from_config(config) as db:
        for (user_id,) in db.execute(Sql.raw("SELECT id FROM users")):
            seen.append(user_id)
            db.fetchone(Sql.raw("SELECT name FROM users WHERE id = ?"), (user_id,))
    assert seen == [1, 2]


def test_template_shared_across_dbs(tmp_path):
    """Test a template resolves against the Db running it, not the first one."""
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "q.sql").write_text(f"SELECT '{name}'")
    sql = Sql.template("q.sql")
    with Db(":memory:", sql_templates_dir=tmp_path / "a") as db:
        assert db.fetchone(sql) == ("a",)
    with Db(":memory:", sql_templates_dir=tmp_path / "b") as db:
        assert db.fetchone(sql) == ("b",)


def test_template_filename_with_double_dots(tmp_path):
    """Test a filename containing .. that stays in the directory is allowed."""
    (tmp_path / "v1..final.sql").write_text("SELECT 1")
    assert Sql.template("v1..final.sql", path=tmp_path).load_query() == "SELECT 1"


def test_db_context_manager_commits_on_clean_exit(config):
    """Test changes are committed when the context exits without error."""
    with Db.from_config(config) as db:
        db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
    with Db.from_config(config) as db:
        result = db.fetchone(Sql.raw("SELECT id FROM users WHERE id = 3"))
    assert result == (3,)


def test_db_close_discards_uncommitted(config):
    """Test close() without commit discards pending changes."""
    db = Db.from_config(config)
    db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
    db.close()
    with Db.from_config(config) as db:
        result = db.fetchone(Sql.raw("SELECT id FROM users WHERE id = 3"))
    assert result is None


def test_namedtuple_factory_invalid_column_names(config):
    """Test columns that are not valid identifiers are renamed by position."""
    with Db.from_config(config, row_factory=namedtuple_factory) as db:
        result = db.fetchone(Sql.raw("SELECT COUNT(*), id, id FROM users"))
    assert result._fields == ("_0", "id", "_2")
    assert result[0] == 2


def test_named_params(config):
    """Test binding named parameters."""
    sql = Sql.raw("SELECT name FROM users WHERE id = :id")
    with Db.from_config(config) as db:
        assert db.fetchone(sql, {"id": 2}) == ("John",)


def test_pragmas(config):
    """Test pragmas are applied to the connection."""
    with Db.from_config(config, pragmas=RECOMMENDED_PRAGMAS) as db:
        assert db.fetchval(Sql.raw("PRAGMA foreign_keys")) == 1
        assert db.fetchval(Sql.raw("PRAGMA journal_mode")) == "wal"
    with Db.from_config(config) as db:
        assert db.fetchval(Sql.raw("PRAGMA foreign_keys")) == 0


def test_pragmas_reject_injection():
    """Test pragma names and values are validated."""
    with raises(ValueError, match="Invalid pragma name"):
        Db(":memory:", pragmas={"foreign_keys; DROP TABLE users": 1})
    with raises(ValueError, match="Invalid value for pragma"):
        Db(":memory:", pragmas={"journal_mode": "wal; DROP TABLE users"})


def test_fetchval(config):
    """Test fetchval returns a scalar whatever the row factory."""
    count = Sql.raw("SELECT COUNT(*) FROM users")
    missing = Sql.raw("SELECT id FROM users WHERE id = 99")
    with Db.from_config(config, row_factory=dict_factory) as db:
        assert db.fetchval(count) == 2
        assert db.fetchval(missing) is None
        # the connection row factory is left untouched
        assert db.fetchone(count) == {"COUNT(*)": 2}


def test_dataclass_factory(config):
    """Test rows are returned as dataclass instances."""

    @dataclass
    class User:
        id: int
        name: str

    with Db.from_config(config, row_factory=dataclass_factory(User)) as db:
        results = db.fetchall(Sql.raw("SELECT id, name FROM users"))
    assert results == [User(1, "Alice"), User(2, "John")]


def test_transaction_commits_when_outermost(config):
    """Test an outermost transaction block commits on success."""
    db = Db.from_config(config)
    with db.transaction():
        db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
    db.close()  # close without commit, the block already committed
    with Db.from_config(config) as db:
        assert db.fetchval(Sql.raw("SELECT COUNT(*) FROM users")) == 3


def test_transaction_nested_rollback(config):
    """Test a failing inner block only undoes its own changes."""
    with Db.from_config(config) as db:
        with db.transaction():
            db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
            with raises(RuntimeError):
                with db.transaction():
                    db.execute(Sql.raw("INSERT INTO users VALUES (4, 'Bob')"))
                    raise RuntimeError
            db.execute(Sql.raw("INSERT INTO users VALUES (5, 'Eve')"))
    with Db.from_config(config) as db:
        assert db.fetchall(Sql.raw("SELECT id FROM users")) == [(1,), (2,), (3,), (5,)]


def test_transaction_rollback_keeps_outer_work(config):
    """Test a failing block inside an implicit transaction keeps prior work."""
    with Db.from_config(config) as db:
        db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
        with raises(RuntimeError):
            with db.transaction():
                db.execute(Sql.raw("INSERT INTO users VALUES (4, 'Bob')"))
                raise RuntimeError
    with Db.from_config(config) as db:
        assert db.fetchall(Sql.raw("SELECT id FROM users")) == [(1,), (2,), (3,)]


def test_transaction_autocommit(config):
    """Test transaction blocks work in autocommit mode."""
    with Db.from_config(config, autocommit=True) as db:
        with raises(RuntimeError):
            with db.transaction():
                db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
                raise RuntimeError
        assert db.fetchval(Sql.raw("SELECT COUNT(*) FROM users")) == 2


def test_migrate(config, tmp_path):
    """Test migrations apply in version order, once."""
    (tmp_path / "002_add_email.sql").write_text("ALTER TABLE pets ADD email TEXT;")
    (tmp_path / "001_create_pets.sql").write_text(
        "CREATE TABLE pets (id INTEGER PRIMARY KEY);\nINSERT INTO pets VALUES (1)"
    )
    (tmp_path / "notes.txt").write_text("ignored")
    with Db.from_config(config) as db:
        assert db.migrate(tmp_path) == 2
        assert db.migrate(tmp_path) == 0
        assert db.fetchval(Sql.raw("PRAGMA user_version")) == 2
        assert db.fetchone(Sql.raw("SELECT id, email FROM pets")) == (1, None)
        (tmp_path / "003_more.sql").write_text("INSERT INTO pets (id) VALUES (2);")
        assert db.migrate(tmp_path) == 1


def test_migrate_failure_is_atomic(config, tmp_path):
    """Test a failing migration is rolled back entirely, earlier ones stay."""
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE pets (id INTEGER);")
    (tmp_path / "002_bad.sql").write_text(
        "CREATE TABLE toys (id INTEGER);\nINSERT INTO nope VALUES (1);"
    )
    with Db.from_config(config) as db:
        with raises(OperationalError):
            db.migrate(tmp_path)
        assert db.fetchval(Sql.raw("PRAGMA user_version")) == 1
        tables = Sql.raw(
            "SELECT name FROM sqlite_master WHERE name IN ('pets', 'toys')"
        )
        assert db.fetchall(tables) == [("pets",)]


def test_migrate_duplicate_version(config, tmp_path):
    """Test two files with the same version are rejected."""
    (tmp_path / "001_a.sql").write_text("SELECT 1;")
    (tmp_path / "1_b.sql").write_text("SELECT 1;")
    with Db.from_config(config) as db:
        with raises(ValueError, match="Invalid or duplicate migration"):
            db.migrate(tmp_path)


def test_migrate_refuses_open_transaction(config, tmp_path):
    """Test migrating with pending changes is refused."""
    with Db.from_config(config) as db:
        db.execute(Sql.raw("INSERT INTO users VALUES (3, 'Kate')"))
        with raises(RuntimeError, match="open transaction"):
            db.migrate(tmp_path)


def test_migrate_with_row_factory_and_autocommit(config, tmp_path):
    """Test migrating works whatever the row factory and commit mode."""
    (tmp_path / "001_pets.sql").write_text("CREATE TABLE pets (id INTEGER);")
    with Db.from_config(config, row_factory=dict_factory, autocommit=True) as db:
        assert db.migrate(tmp_path) == 1
        assert db.fetchval(Sql.raw("PRAGMA user_version")) == 1


def test_migrate_statement_splitting(config, tmp_path):
    """Test semicolons in strings, comments and triggers do not split."""
    (tmp_path / "001_pets.sql").write_text(
        """-- pets; and their log
        CREATE TABLE pets (name TEXT);
        CREATE TABLE log (msg TEXT);
        CREATE TRIGGER pets_log AFTER INSERT ON pets BEGIN
            INSERT INTO log VALUES ('added; ' || NEW.name);
            INSERT INTO log VALUES ('done');
        END;
        INSERT INTO pets VALUES ('Rex; the dog')
        -- trailing comment; no newline"""
    )
    with Db.from_config(config) as db:
        assert db.migrate(tmp_path) == 1
        assert db.fetchval(Sql.raw("SELECT name FROM pets")) == "Rex; the dog"
        assert db.fetchall(Sql.raw("SELECT msg FROM log")) == [
            ("added; Rex; the dog",),
            ("done",),
        ]


def test_migrate_skips_version_applied_by_another_connection(config, tmp_path):
    """Test a migration applied elsewhere after the first read is skipped."""
    (tmp_path / "001_pets.sql").write_text("CREATE TABLE pets (id INTEGER);")
    with Db.from_config(config) as db, Db.from_config(config) as other:
        original = db._scalar
        calls = []

        def stale_first_read(query, params=()):
            # first read sees version 0, then the other connection migrates
            value = original(query, params)
            if not calls:
                calls.append(1)
                assert other.migrate(tmp_path) == 1
            return value

        db._scalar = stale_first_read
        assert db.migrate(tmp_path) == 0
