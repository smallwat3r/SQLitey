# SQLitey

SQLitey is a lightweight and flexible wrapper around SQLite, designed to streamline database access using configuration files, SQL templates, and custom row factories.

Key Features:
- Configuration-driven setup for database paths and SQL templates
- Support for SQL template files to keep queries organized
- Customizable row factories (e.g., return rows as namedtuples)
- Support for both templated and raw SQL queries
- Optional config usage for quick, one-off database access

## Exampe usage

### Using a Config File

Define a configuration with the database path and the directory for SQL templates:

``` python
from pathlib import Path
from sqlitey import Db, DbPathConfig, Sql, namedtuple_factory

dir = Path(__file__).resolve().parent
config = DbPathConfig(
    database=dir / "db.sqlite3",
    sql_templates_dir=dir / "sql"
)

with Db.from_config(config, row_factory=namedtuple_factory) as db:
    result = db.fetchone(Sql.template("get_user_by_id.sql"), (3,))
    print(result.id, result.name)
```

### Executing Raw SQL

You can also use raw SQL directly:

``` python
with Db.from_config(config, timeout=15) as db:
    db.commit(Sql.raw("INSERT INTO users VALUES (10, 'John');"))
```

### Without a Config File

Skip the config and use the database path directly:

``` python
with Db("db.sqlite3", autocommit=True) as db:
    db.execute(Sql.raw("UPDATE users SET name = 'Johnny' WHERE id = 10;"))

with Db("db.sqlite3") as db:
    sql = Sql.template("get_user_by_id.sql", path=Path(__file__).resolve().parent / "sql")
    result = db.fetchone(sql, (3,))
```

### More examples

See more examples in [tests](./tests/test_sqlight.py)
