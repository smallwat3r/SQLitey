import sqlite3
from collections import namedtuple
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol, Self, TypeAlias, runtime_checkable


@dataclass(frozen=True)
class DbConfig:
    """Database path configurations."""

    # database filepath
    database: Path
    # directory storing sql templates
    sql_templates_dir: Path | None = None


@lru_cache
def _read_sql_template(filename: str, path: Path) -> str:
    return (path / filename).read_text().strip()


@runtime_checkable
class _SqlRawProtocol(Protocol):
    _query: Callable


@runtime_checkable
class _SqlTemplateProtocol(Protocol):
    _query: Callable
    filename: str


class Sql:
    """Represent a SQL query."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("Direct instantiation is not allowed, use a classmethod.")

    @property
    def query(self) -> str:
        if isinstance(self, _SqlTemplateProtocol):
            # path should always be set if we read from a template
            if not hasattr(self, "path"):
                raise ValueError("No template path configured")
            return self._query(self.filename, getattr(self, "path"))
        assert isinstance(self, _SqlRawProtocol)
        return self._query()

    @classmethod
    def raw(cls, query: str) -> Self:
        self = object.__new__(cls)
        setattr(self, "_query", lambda: query)
        return self

    @classmethod
    def template(cls, filename: str, *, path: Path | None = None) -> Self:
        self = object.__new__(cls)
        setattr(self, "_query", _read_sql_template)
        setattr(self, "filename", filename)
        # can also be deferred from the config if not set here
        if path:
            setattr(self, "path", path)
        return self


SqlRow: TypeAlias = Any
RowFactory: TypeAlias = Callable[[sqlite3.Cursor, sqlite3.Row], SqlRow]


def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> SqlRow:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def namedtuple_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> SqlRow:
    Row = namedtuple("Row", [str(col[0]) for col in cursor.description])  # type: ignore
    return Row(*row)


class _SafeCursor:
    """Proxy to protect `cursor.execute` to be accessed directly."""

    def __init__(self, safe_cursor: sqlite3.Cursor) -> None:
        self._safe_cursor = safe_cursor

    def __getattr__(self, name: str) -> Any:
        if name == "execute":
            raise AttributeError(
                "Cannot use db.cursor.execute(), use db.execute() instead"
            )
        return getattr(self._safe_cursor, name)


class Db:
    """SQLite wrapper class."""

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
        self.cursor = _SafeCursor(self.conn.cursor())
        self._sql_templates_dir = sql_templates_dir

    @classmethod
    def from_config(cls, config: DbConfig, **kwargs) -> Self:
        return cls(
            config.database,
            sql_templates_dir=config.sql_templates_dir,
            **kwargs,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args, **kwargs) -> None:
        self.conn.close()

    def execute(self, sql: Sql, *args) -> SqlRow:
        if hasattr(sql, "template") and not hasattr(sql, "path"):
            # path is deferred, lets set it from the config
            setattr(sql, "path", self._sql_templates_dir)
        return self.cursor._safe_cursor.execute(sql.query, *args)

    def fetchone(self, sql: Sql, *args) -> SqlRow:
        return self.execute(sql, *args).fetchone()

    def fetchall(self, sql: Sql, *args) -> list[SqlRow]:
        return self.execute(sql, *args).fetchall()

    def commit(self, sql: Sql, *args) -> None:
        self.execute(sql, *args)
        self.conn.commit()
