"""Sqlitey - A lightweight SQLite wrapper with SQL injection protection.

This module provides a safe interface for SQLite database operations by
enforcing the use of the Sql class for all queries, preventing direct
string-based SQL execution.

Example:
    >>> from sqlitey import Db, Sql
    >>> with Db("mydb.sqlite") as db:
    ...     users = db.fetchall(Sql.raw("SELECT * FROM users"))
"""

import sqlite3
from collections import namedtuple
from dataclasses import dataclass
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Callable, Self, TypeAlias

__all__ = [
    "Db",
    "DbPathConfig",
    "Sql",
    "dict_factory",
    "namedtuple_factory",
    "RowFactory",
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
        ValueError: If the filename attempts path traversal.
    """
    # Validate filename to prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise ValueError(f"Invalid template filename: {filename}")

    file_path = template_path / filename
    # Ensure resolved path is within template directory
    try:
        file_path.resolve().relative_to(template_path.resolve())
    except ValueError:
        raise ValueError(f"Template path traversal detected: {filename}") from None

    try:
        return file_path.read_text().strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"SQL template not found: {filename} in {template_path}"
        ) from None


class Sql:
    """Represents a SQL query, either inline or from a template file.

    Use the class methods `raw()` or `template()` to create instances.
    Direct instantiation is discouraged.

    Example:
        >>> sql = Sql.raw("SELECT * FROM users WHERE id = ?")
        >>> sql = Sql.template("get_users.sql")
    """

    def __init__(self, query_loader: Callable, **kwargs) -> None:
        self._query_loader = query_loader
        self._is_templated = False
        self._store = kwargs

    @property
    def has_template_path(self) -> bool:
        """Return True if this is a template with a configured path."""
        return bool(self._is_templated and self._store.get("template_path"))

    def set_template_path(self, template_path: Path) -> None:
        """Set the template directory path for deferred template resolution."""
        if self._is_templated:
            self._store["template_path"] = template_path

    def load_query(self) -> str:
        """Load and return the SQL query string.

        Raises:
            ValueError: If this is a template without a configured path.
        """
        if self._is_templated and not self.has_template_path:
            raise ValueError("No template path configured")
        return self._query_loader(**self._store)

    @classmethod
    def raw(cls, query: str) -> Self:
        """Create a Sql instance from an inline query string.

        Args:
            query: The SQL query string.

        Returns:
            A Sql instance wrapping the query.
        """
        return cls(lambda: query)

    @classmethod
    def template(cls, filename: str, *, path: Path | None = None) -> Self:
        """Create a Sql instance from a template file.

        The template path can be provided directly or deferred to be set
        later via the Db configuration.

        Args:
            filename: Name of the SQL template file.
            path: Optional directory containing the template file.

        Returns:
            A Sql instance that loads from the template file.
        """
        instance = cls(_read_sql_template, template_path=path, filename=filename)
        instance._is_templated = True
        return instance


#: Type alias for database row data returned by queries.
SqlRow: TypeAlias = tuple[Any, ...] | dict[str, Any] | Any

#: Type alias for row factory functions that transform raw rows.
RowFactory: TypeAlias = Callable[[sqlite3.Cursor, sqlite3.Row], SqlRow]


def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    """Row factory that returns rows as dictionaries.

    Example:
        >>> with Db("mydb.sqlite", row_factory=dict_factory) as db:
        ...     user = db.fetchone(Sql.raw("SELECT id, name FROM users"))
        ...     print(user["name"])
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@lru_cache(maxsize=128)
def _make_row_class(fields: tuple[str, ...]) -> type[tuple[Any, ...]]:
    """Create and cache a namedtuple class for the given field names."""
    return namedtuple("Row", fields)


def namedtuple_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> tuple[Any, ...]:
    """Row factory that returns rows as namedtuples.

    Example:
        >>> with Db("mydb.sqlite", row_factory=namedtuple_factory) as db:
        ...     user = db.fetchone(Sql.raw("SELECT id, name FROM users"))
        ...     print(user.name)
    """
    fields = tuple(col[0] for col in cursor.description)
    return _make_row_class(fields)(*row)


_HOOKED_METHODS = frozenset({"execute", "executemany", "executescript"})


class _SafeCursor:
    """Cursor proxy that blocks direct access to execute methods.

    This prevents bypassing the Sql class by calling cursor.execute() directly.
    All other cursor attributes are proxied through to the underlying cursor.
    """

    __slots__ = ("__cursor",)

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        object.__setattr__(self, "_SafeCursor__cursor", cursor)

    def __getattr__(self, name: str) -> Any:
        if name in _HOOKED_METHODS:
            raise AttributeError(f"Cannot access {name} from cursor directly")
        return getattr(self.__cursor, name)


class Db:
    """SQLite database wrapper with SQL injection protection.

    All queries must be wrapped in a Sql object, preventing direct string
    execution. Supports both inline queries and SQL template files.

    Args:
        *args: Positional arguments passed to sqlite3.connect().
        row_factory: Optional factory function to transform result rows.
        sql_templates_dir: Optional directory for SQL template files.
        autocommit: If True, disable transaction management.
        **kwargs: Keyword arguments passed to sqlite3.connect().

    Example:
        >>> with Db("mydb.sqlite", row_factory=dict_factory) as db:
        ...     db.commit(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Alice",))
        ...     users = db.fetchall(Sql.raw("SELECT * FROM users"))
    """

    def __init__(
        self,
        *args,
        row_factory: RowFactory | None = None,
        sql_templates_dir: Path | None = None,
        autocommit: bool = False,
        **kwargs,
    ) -> None:
        if autocommit:
            kwargs["isolation_level"] = None
        self.conn = sqlite3.connect(*args, **kwargs)
        if row_factory:
            self.conn.row_factory = row_factory
        self._cursor = _SafeCursor(self.conn.cursor())
        self._sql_templates_dir = sql_templates_dir
        self._method_cache: dict[str, Callable] = {}

    @classmethod
    def from_config(cls, config: DbPathConfig, **kwargs) -> Self:
        """Create a Db instance from a DbPathConfig.

        Args:
            config: Database path configuration.
            **kwargs: Additional arguments passed to the constructor.
        """
        return cls(
            config.database,
            sql_templates_dir=config.sql_templates_dir,
            **kwargs,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self.conn.close()
        except Exception:
            # Suppress close errors to avoid masking the original exception
            if exc_type is None:
                raise

    def _pre_execute_hook(self, sql: Sql) -> None:
        """Set deferred template path from config if not already set."""
        if not sql.has_template_path and self._sql_templates_dir:
            sql.set_template_path(self._sql_templates_dir)

    def __getattribute__(self, name: str) -> Any:
        attr = super().__getattribute__(name)
        # inject hook before running sensitive methods
        if name in _HOOKED_METHODS:
            # Cache wrapper functions to avoid creating new ones on each access
            cache = super().__getattribute__("_method_cache")
            if name not in cache:

                @wraps(attr)
                def wrapper(*args, **kwargs):
                    self._pre_execute_hook(args[0])
                    return attr(*args, **kwargs)

                cache[name] = wrapper
            return cache[name]
        return attr

    def execute(self, sql: Sql, *args) -> sqlite3.Cursor:
        """Execute a SQL query and return the cursor.

        Args:
            sql: The Sql object containing the query.
            *args: Parameters to bind to the query.
        """
        return self._cursor._SafeCursor__cursor.execute(sql.load_query(), *args)

    def executemany(self, sql: Sql, *args) -> sqlite3.Cursor:
        """Execute a SQL query against multiple parameter sets.

        Args:
            sql: The Sql object containing the query.
            *args: Sequence of parameter sets.
        """
        return self._cursor._SafeCursor__cursor.executemany(sql.load_query(), *args)

    def executescript(self, sql: Sql) -> sqlite3.Cursor:
        """Execute multiple SQL statements as a script.

        Args:
            sql: The Sql object containing the script.
        """
        return self._cursor._SafeCursor__cursor.executescript(sql.load_query())

    def fetchone(self, sql: Sql, *args) -> SqlRow | None:
        """Execute a query and return the first result row, or None.

        Args:
            sql: The Sql object containing the query.
            *args: Parameters to bind to the query.
        """
        return self.execute(sql, *args).fetchone()

    def fetchall(self, sql: Sql, *args) -> list[SqlRow]:
        """Execute a query and return all result rows.

        Args:
            sql: The Sql object containing the query.
            *args: Parameters to bind to the query.
        """
        return self.execute(sql, *args).fetchall()

    def commit(self, sql: Sql, *args) -> None:
        """Execute a query and commit the transaction.

        Args:
            sql: The Sql object containing the query.
            *args: Parameters to bind to the query.
        """
        self.execute(sql, *args)
        self.conn.commit()
