"""Sqlitey - A lightweight SQLite wrapper.

Queries are passed around as Sql objects, either inline or loaded from
SQL template files. Sql.raw() is typed as LiteralString, so type checkers
that enforce it (pyright does, mypy currently treats it as str) flag
queries built from dynamic strings. This is a static check only, nothing
is validated at runtime, always pass values as bound parameters.

Example:
    >>> from sqlitey import Db, Sql
    >>> with Db("mydb.sqlite") as db:
    ...     users = db.fetchall(Sql.raw("SELECT * FROM users"))
"""

import os
import re
import sqlite3
from collections import namedtuple
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, LiteralString, Self, TypeAlias, TypeVar, overload

__all__ = [
    "Db",
    "DbPathConfig",
    "Sql",
    "dataclass_factory",
    "dict_factory",
    "namedtuple_factory",
    "RECOMMENDED_PRAGMAS",
    "RowFactory",
    "SqlParams",
    "SqlRow",
]


@dataclass(frozen=True)
class DbPathConfig:
    """Configuration for database and SQL template paths.

    Attributes:
        database: Path to the SQLite database file.
        sql_templates_dir: Optional directory containing SQL template files.
    """

    database: Path
    sql_templates_dir: Path | None = None


@lru_cache(maxsize=128)
def _read_sql_template(filename: str, template_path: Path) -> str:
    """Read and cache SQL template files.

    Raises:
        FileNotFoundError: If the template file does not exist.
        ValueError: If the filename resolves outside the template directory.
    """
    file_path = (template_path / filename).resolve()
    if not file_path.is_relative_to(template_path.resolve()):
        raise ValueError(f"Template path traversal detected: {filename}")

    try:
        return file_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"SQL template not found: {filename} in {template_path}"
        ) from None


@dataclass(frozen=True, slots=True)
class Sql:
    """Represents a SQL query, either inline or from a template file.

    Instances are immutable, so they are safe to define once at module
    level and share across databases. Use the class methods `raw()` or
    `template()` to create instances.

    Example:
        >>> sql = Sql.raw("SELECT * FROM users WHERE id = ?")
        >>> sql = Sql.template("get_users.sql")
    """

    query: str | None = None
    filename: str | None = None
    path: Path | None = None

    def load_query(self, templates_dir: Path | None = None) -> str:
        """Load and return the SQL query string.

        Args:
            templates_dir: Directory to resolve a template from, used when
                the template was created without its own path.

        Raises:
            ValueError: If this is a template and no path is available.
        """
        if self.query is not None:
            return self.query
        if self.filename is None:
            raise ValueError("Empty Sql, use Sql.raw() or Sql.template()")
        template_path = self.path or templates_dir
        if template_path is None:
            raise ValueError("No template path configured")
        return _read_sql_template(self.filename, template_path)

    @classmethod
    def raw(cls, query: LiteralString) -> Self:
        """Create a Sql instance from an inline query string.

        The query is typed as a literal string, so type checkers enforcing
        LiteralString reject strings built at runtime. Pass values as
        bound parameters.

        Args:
            query: The SQL query string.
        """
        return cls(query=query)

    @classmethod
    def template(cls, filename: str, *, path: Path | None = None) -> Self:
        """Create a Sql instance from a template file.

        The template path can be provided directly, otherwise the
        templates directory of the Db running the query is used.

        Args:
            filename: Name of the SQL template file.
            path: Optional directory containing the template file.
        """
        return cls(filename=filename, path=path)


#: Type alias for database row data, its shape depends on the row factory.
SqlRow: TypeAlias = Any

#: Type alias for parameters bound to a query.
SqlParams: TypeAlias = Sequence[Any] | Mapping[str, Any]

_StrPath: TypeAlias = str | os.PathLike[str]

#: Type alias for row factory functions that transform raw rows.
RowFactory: TypeAlias = Callable[[sqlite3.Cursor, tuple[Any, ...]], SqlRow]


def dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    """Row factory that returns rows as dictionaries.

    Example:
        >>> with Db("mydb.sqlite", row_factory=dict_factory) as db:
        ...     user = db.fetchone(Sql.raw("SELECT id, name FROM users"))
        ...     print(user["name"])
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@lru_cache(maxsize=128)
def _make_row_class(fields: tuple[str, ...]) -> Callable[..., tuple[Any, ...]]:
    """Create and cache a namedtuple class for the given field names."""
    # rename=True turns invalid or duplicate column names, such as
    # COUNT(*), into positional names (_0, _1, ...) instead of raising
    return namedtuple("Row", fields, rename=True)


def namedtuple_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> Any:
    """Row factory that returns rows as namedtuples.

    Columns whose names are not valid identifiers (for example COUNT(*))
    are renamed to their position, _0, _1 and so on. Alias them in the
    query to get a proper name.

    Example:
        >>> with Db("mydb.sqlite", row_factory=namedtuple_factory) as db:
        ...     user = db.fetchone(Sql.raw("SELECT id, name FROM users"))
        ...     print(user.name)
    """
    fields = tuple(col[0] for col in cursor.description)
    return _make_row_class(fields)(*row)


_T = TypeVar("_T")
_RowT = TypeVar("_RowT")

# A row factory whose row type is known, so per query results can be typed
_TypedRowFactory: TypeAlias = Callable[[sqlite3.Cursor, tuple[Any, ...]], _T]


def dataclass_factory(cls: Callable[..., _T]) -> _TypedRowFactory[_T]:
    """Build a row factory returning instances of the given class.

    Each row is passed to the class as keyword arguments, so the column
    names must match its fields. Works with dataclasses and any other
    class accepting its fields as keyword arguments.

    A class maps to one shape of row, so this is usually passed per
    query rather than to Db.

    Example:
        >>> @dataclass
        ... class User:
        ...     id: int
        ...     name: str
        >>> with Db("mydb.sqlite") as db:
        ...     user = db.fetchone(
        ...         Sql.raw("SELECT id, name FROM users"),
        ...         row_factory=dataclass_factory(User),
        ...     )
        ...     print(user.name)
    """

    def factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> _T:
        return cls(**{col[0]: value for col, value in zip(cursor.description, row)})

    return factory


#: Pragmas most applications want: enforced foreign keys, and WAL
#: journalling so readers do not block the writer.
RECOMMENDED_PRAGMAS: Mapping[str, str | int] = {
    "foreign_keys": True,
    "journal_mode": "wal",
    "synchronous": "normal",
}

_PRAGMA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PRAGMA_TEXT_VALUE = re.compile(r"[A-Za-z0-9_]+")
_MIGRATION_FILE = re.compile(r"(\d+)_.+\.sql")


def _pragma_statement(name: str, value: str | int) -> str:
    """Build a PRAGMA statement, rejecting anything but plain tokens.

    PRAGMA does not support bound parameters, so names and values are
    validated strictly before being formatted into the statement.
    """
    if not _PRAGMA_NAME.fullmatch(name):
        raise ValueError(f"Invalid pragma name: {name!r}")
    if isinstance(value, int):
        return f"PRAGMA {name} = {int(value)}"
    if isinstance(value, str) and _PRAGMA_TEXT_VALUE.fullmatch(value):
        return f"PRAGMA {name} = {value}"
    raise ValueError(f"Invalid value for pragma {name}: {value!r}")


def _split_statements(script: str) -> Iterator[str]:
    """Split a SQL script into single statements.

    Relies on sqlite3.complete_statement, which understands string
    literals, comments and trigger bodies, so semicolons inside those do
    not split a statement.
    """
    statement = ""
    for part in script.split(";"):
        statement += part + ";"
        if sqlite3.complete_statement(statement):
            if statement.strip("; \t\r\n"):
                yield statement
            statement = ""
    # whatever is left is a trailing comment, or an unterminated statement
    # that SQLite will reject with a proper error
    if statement.strip("; \t\r\n"):
        yield statement


class Db(Generic[_RowT]):
    """SQLite database wrapper running queries wrapped in Sql objects.

    Supports both inline queries and SQL template files. Used as a context
    manager, it commits on a clean exit, rolls back on an exception, and
    closes the connection either way.

    The class is generic over its default row type, inferred from the row
    factory given here, so fetchone() and fetchall() are typed accordingly.

    Args:
        database: Path to the database file, or ":memory:".
        *args: Extra positional arguments passed to sqlite3.connect().
        row_factory: Optional factory function to transform result rows,
            can be overridden per query.
        sql_templates_dir: Optional directory for SQL template files.
        autocommit: If True, disable transaction management.
        pragmas: Optional pragmas to set on the connection, for example
            RECOMMENDED_PRAGMAS or {"foreign_keys": True}.
        readonly: If True, open an existing database file read-only,
            any write raises sqlite3.OperationalError.
        **kwargs: Keyword arguments passed to sqlite3.connect().

    Example:
        >>> with Db("mydb.sqlite", row_factory=dict_factory) as db:
        ...     db.execute(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Alice",))
        ...     users = db.fetchall(Sql.raw("SELECT * FROM users"))
    """

    @overload
    def __init__(
        self: "Db[tuple[Any, ...]]",
        database: _StrPath,
        *args: Any,
        row_factory: None = None,
        sql_templates_dir: Path | None = None,
        autocommit: bool = False,
        pragmas: Mapping[str, str | int] | None = None,
        readonly: bool = False,
        **kwargs: Any,
    ) -> None: ...

    @overload
    def __init__(
        self,
        database: _StrPath,
        *args: Any,
        row_factory: _TypedRowFactory[_RowT],
        sql_templates_dir: Path | None = None,
        autocommit: bool = False,
        pragmas: Mapping[str, str | int] | None = None,
        readonly: bool = False,
        **kwargs: Any,
    ) -> None: ...

    def __init__(
        self,
        database: _StrPath,
        *args: Any,
        row_factory: RowFactory | None = None,
        sql_templates_dir: Path | None = None,
        autocommit: bool = False,
        pragmas: Mapping[str, str | int] | None = None,
        readonly: bool = False,
        **kwargs: Any,
    ) -> None:
        if autocommit:
            kwargs["isolation_level"] = None
        if readonly:
            if kwargs.get("uri"):
                raise ValueError("readonly cannot be combined with uri=True")
            # as_uri() percent-encodes the path, so it cannot inject options
            database = f"{Path(database).resolve().as_uri()}?mode=ro"
            kwargs["uri"] = True
        statements = [_pragma_statement(k, v) for k, v in (pragmas or {}).items()]
        self.conn = sqlite3.connect(database, *args, **kwargs)
        try:
            for statement in statements:
                self.conn.execute(statement)
        except BaseException:
            self.conn.close()
            raise
        if row_factory is not None:
            self.conn.row_factory = row_factory
        self._sql_templates_dir = sql_templates_dir
        self._savepoint_depth = 0

    @overload
    @classmethod
    def from_config(
        cls, config: DbPathConfig, *, row_factory: None = None, **kwargs: Any
    ) -> "Db[tuple[Any, ...]]": ...

    @overload
    @classmethod
    def from_config(
        cls,
        config: DbPathConfig,
        *,
        row_factory: _TypedRowFactory[_T],
        **kwargs: Any,
    ) -> "Db[_T]": ...

    @classmethod
    def from_config(
        cls,
        config: DbPathConfig,
        *,
        row_factory: RowFactory | None = None,
        **kwargs: Any,
    ) -> "Db[Any]":
        """Create a Db instance from a DbPathConfig.

        Args:
            config: Database path configuration.
            row_factory: Optional factory function to transform result rows.
            **kwargs: Additional arguments passed to the constructor.
        """
        db = cls(
            config.database,
            sql_templates_dir=config.sql_templates_dir,
            **kwargs,
        )
        if row_factory is not None:
            db.conn.row_factory = row_factory
        return db

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.close()

    def close(self) -> None:
        """Close the connection, discarding any uncommitted changes."""
        self.conn.close()

    def _load(self, sql: Sql) -> str:
        return sql.load_query(self._sql_templates_dir)

    def _forbid_in_transaction_block(self, action: str) -> None:
        # committing releases every savepoint, breaking the block atomicity
        if self._savepoint_depth:
            raise RuntimeError(f"Cannot call {action} inside a transaction() block")

    def execute(
        self,
        sql: Sql,
        params: SqlParams = (),
        *,
        row_factory: RowFactory | None = None,
    ) -> sqlite3.Cursor:
        """Execute a SQL query and return a new cursor.

        Args:
            sql: The Sql object containing the query.
            params: Parameters to bind to the query.
            row_factory: Row factory for this query only, defaults to the
                one given to Db.
        """
        cursor = self.conn.cursor()
        if row_factory is not None:
            cursor.row_factory = row_factory
        return cursor.execute(self._load(sql), params)

    def executemany(
        self, sql: Sql, seq_of_params: Iterable[SqlParams]
    ) -> sqlite3.Cursor:
        """Execute a SQL query against multiple parameter sets.

        Args:
            sql: The Sql object containing the query.
            seq_of_params: Parameter sets to bind, one per execution.
        """
        return self.conn.executemany(self._load(sql), seq_of_params)

    def executescript(self, sql: Sql) -> sqlite3.Cursor:
        """Execute multiple SQL statements as a script.

        sqlite3 commits any open transaction before running a script, so
        this is refused inside a transaction() block.

        Args:
            sql: The Sql object containing the script.

        Raises:
            RuntimeError: If called inside a transaction() block.
        """
        self._forbid_in_transaction_block("executescript()")
        return self.conn.executescript(self._load(sql))

    @overload
    def fetchone(
        self, sql: Sql, params: SqlParams = ..., *, row_factory: _TypedRowFactory[_T]
    ) -> _T | None: ...

    @overload
    def fetchone(
        self, sql: Sql, params: SqlParams = ..., *, row_factory: None = None
    ) -> _RowT | None: ...

    def fetchone(
        self,
        sql: Sql,
        params: SqlParams = (),
        *,
        row_factory: RowFactory | None = None,
    ) -> SqlRow | None:
        """Execute a query and return the first result row, or None.

        Args:
            sql: The Sql object containing the query.
            params: Parameters to bind to the query.
            row_factory: Row factory for this query only, defaults to the
                one given to Db.
        """
        return self.execute(sql, params, row_factory=row_factory).fetchone()

    @overload
    def fetchall(
        self, sql: Sql, params: SqlParams = ..., *, row_factory: _TypedRowFactory[_T]
    ) -> list[_T]: ...

    @overload
    def fetchall(
        self, sql: Sql, params: SqlParams = ..., *, row_factory: None = None
    ) -> list[_RowT]: ...

    def fetchall(
        self,
        sql: Sql,
        params: SqlParams = (),
        *,
        row_factory: RowFactory | None = None,
    ) -> list[SqlRow]:
        """Execute a query and return all result rows.

        Args:
            sql: The Sql object containing the query.
            params: Parameters to bind to the query.
            row_factory: Row factory for this query only, defaults to the
                one given to Db.
        """
        return self.execute(sql, params, row_factory=row_factory).fetchall()

    def fetchval(self, sql: Sql, params: SqlParams = ()) -> Any:
        """Execute a query and return the first column of the first row.

        Returns None if the query yields no row. The row factory is not
        applied.

        Args:
            sql: The Sql object containing the query.
            params: Parameters to bind to the query.
        """
        return self._scalar(self._load(sql), params)

    def _scalar(self, query: str, params: SqlParams = ()) -> Any:
        # dedicated cursor without the row factory, so row[0] always works
        cursor = self.conn.cursor()
        cursor.row_factory = None
        row = cursor.execute(query, params).fetchone()
        return None if row is None else row[0]

    @contextmanager
    def transaction(self) -> Iterator[Self]:
        """Run a block atomically, using a savepoint.

        If the block raises, its changes are rolled back and the exception
        propagates. Blocks can be nested, an inner failure only undoes the
        inner block. When no transaction is open yet, the outermost block
        commits on success, otherwise its changes are committed along with
        the surrounding transaction.

        commit() and executescript() are refused inside a block, as
        committing would end it early.
        """
        name = f"sqlitey_{self._savepoint_depth}"
        self.conn.execute(f"SAVEPOINT {name}")
        self._savepoint_depth += 1
        try:
            yield self
            self.conn.execute(f"RELEASE {name}")
        except BaseException:
            # also reached when the RELEASE itself fails, for example on a
            # deferred constraint, so the block never leaves changes behind
            self.conn.execute(f"ROLLBACK TO {name}")
            self.conn.execute(f"RELEASE {name}")
            raise
        finally:
            self._savepoint_depth -= 1

    def migrate(self, directory: Path) -> int:
        """Apply pending SQL migrations and return how many were applied.

        Migration files are named <version>_<description>.sql, for example
        001_create_users.sql, and run in version order. The current version
        is tracked in PRAGMA user_version, files at or below it are skipped.
        Each migration runs in its own transaction along with its version
        bump, so a failing file leaves the database at the previous version.
        The write lock is taken before each migration, so several processes
        migrating the same database at once apply each file only once.
        Migration files must not contain their own BEGIN or COMMIT.

        Raises:
            RuntimeError: If a transaction is already open.
            ValueError: If two files share a version, or a version is 0.
        """
        if self.conn.in_transaction:
            raise RuntimeError("Cannot migrate inside an open transaction")

        migrations: dict[int, Path] = {}
        for file_path in directory.iterdir():
            match = _MIGRATION_FILE.fullmatch(file_path.name)
            if not match:
                continue
            version = int(match.group(1))
            if version < 1 or version in migrations:
                raise ValueError(f"Invalid or duplicate migration: {file_path.name}")
            migrations[version] = file_path

        current = self._scalar("PRAGMA user_version")
        applied = 0
        for version in sorted(v for v in migrations if v > current):
            script = migrations[version].read_text(encoding="utf-8")
            # take the write lock, then check the version again, another
            # process may have applied this migration in the meantime
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                if self._scalar("PRAGMA user_version") < version:
                    for statement in _split_statements(script):
                        self.conn.execute(statement)
                    self.conn.execute(f"PRAGMA user_version = {version}")
                    applied += 1
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
        return applied

    def commit(self, sql: Sql, params: SqlParams = ()) -> None:
        """Execute a query and commit the transaction.

        Args:
            sql: The Sql object containing the query.
            params: Parameters to bind to the query.

        Raises:
            RuntimeError: If called inside a transaction() block.
        """
        self._forbid_in_transaction_block("commit()")
        self.execute(sql, params)
        self.conn.commit()
