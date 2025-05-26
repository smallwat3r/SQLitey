import sqlite3
from collections import namedtuple
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Self, TypeAlias


@dataclass(frozen=True)
class DbPathConfig:
    """Database path configurations."""

    # database filepath
    database: Path
    # directory storing sql templates
    sql_templates_dir: Path | None = None


@lru_cache
def _read_sql_template(filename: str, template_path: Path) -> str:
    return (template_path / filename).read_text().strip()


class Sql:
    """Represent a SQL query."""

    _is_templated = False

    def __init__(self, query_loader: Callable, **kwargs) -> None:
        self._query_loader = query_loader
        self._store = kwargs

    @property
    def has_template_path(self) -> bool:
        return bool(self._is_templated and self._store.get("template_path"))

    def set_template_path(self, template_path: Path) -> None:
        if self._is_templated:
            self._store["template_path"] = template_path

    def load_query(self) -> str:
        if self._is_templated and not self.has_template_path:
            raise ValueError("No template path configured")
        return self._query_loader(**self._store)

    @classmethod
    def raw(cls, query: str) -> Self:
        return cls(lambda *args, **kwargs: query)

    @classmethod
    def template(cls, filename: str, *, path: Path | None = None) -> Self:
        # path is optional so we can defer setting at a later time, in order to
        # derive its value from a config for example.
        cls_ = cls(_read_sql_template, template_path=path, filename=filename)
        cls_._is_templated = True
        return cls_


SqlRow: TypeAlias = Any
RowFactory: TypeAlias = Callable[[sqlite3.Cursor, sqlite3.Row], SqlRow]


def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> SqlRow:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def namedtuple_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> SqlRow:
    Row = namedtuple("Row", [str(col[0]) for col in cursor.description])  # type: ignore
    return Row(*row)


_HOOKED_METHODS = ("execute", "executemany", "executescript")


class _SafeCursor:
    """Proxy to protect `cursor.execute` to be accessed directly."""

    def __init__(self, safe_cursor: sqlite3.Cursor) -> None:
        self._safe_cursor = safe_cursor

    def __getattr__(self, name: str) -> Any:
        if name in _HOOKED_METHODS:
            raise AttributeError(f"Cannot access {name} from cursor directly")
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
    def from_config(cls, config: DbPathConfig, **kwargs) -> Self:
        return cls(
            config.database,
            sql_templates_dir=config.sql_templates_dir,
            **kwargs,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args, **kwargs) -> None:
        self.conn.close()

    def _pre_execute_hook(self, sql: Sql) -> None:
        if not sql.has_template_path and self._sql_templates_dir:
            # path is deferred, lets set it from the config
            sql.set_template_path(self._sql_templates_dir)

    def __getattribute__(self, name: str) -> Any:
        attr = super().__getattribute__(name)
        # inject hook before running sensitive methods
        if name in _HOOKED_METHODS:

            def wrapper(*args, **kwargs):
                self._pre_execute_hook(args[0])
                return attr(*args, **kwargs)

            return wrapper
        return attr

    def execute(self, sql: Sql, *args) -> SqlRow:
        return self.cursor._safe_cursor.execute(sql.load_query(), *args)

    def executemany(self, sql: Sql, *args) -> SqlRow:
        return self.cursor._safe_cursor.executemany(sql.load_query(), *args)

    def executescript(self, sql: Sql) -> SqlRow:
        return self.cursor._safe_cursor.executescript(sql.load_query())

    def fetchone(self, sql: Sql, *args) -> SqlRow:
        return self.execute(sql, *args).fetchone()

    def fetchall(self, sql: Sql, *args) -> list[SqlRow]:
        return self.execute(sql, *args).fetchall()

    def commit(self, sql: Sql, *args) -> None:
        self.execute(sql, *args)
        self.conn.commit()
