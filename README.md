# SQLitey

SQLitey is a lightweight and flexible wrapper around SQLite, designed to streamline database access using configuration files, SQL templates, and custom row factories.

Key Features:
- Configuration-driven setup for database paths and SQL templates
- Support for SQL template files to keep queries organized
- Customizable row factories (e.g., return rows as namedtuples)
- Support for both templated and raw SQL queries
- Optional config usage for quick, one-off database access

## Installation

```
pip install sqlitey
```

## Quick Start

```python
from sqlitey import Db, Sql

with Db("mydb.sqlite") as db:
    db.commit(Sql.raw("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"))
    db.commit(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Alice",))
    user = db.fetchone(Sql.raw("SELECT * FROM users WHERE id = ?"), (1,))
    print(user)  # (1, 'Alice')
```

## Usage

### Row Factories

Return rows as dictionaries or namedtuples instead of tuples:

```python
from sqlitey import Db, Sql, dict_factory, namedtuple_factory

with Db("mydb.sqlite", row_factory=dict_factory) as db:
    user = db.fetchone(Sql.raw("SELECT * FROM users WHERE id = ?"), (1,))
    print(user["name"])  # 'Alice'

with Db("mydb.sqlite", row_factory=namedtuple_factory) as db:
    user = db.fetchone(Sql.raw("SELECT * FROM users WHERE id = ?"), (1,))
    print(user.name)  # 'Alice'
```

### SQL Templates

Keep SQL queries in separate files for better organization:

```python
from pathlib import Path
from sqlitey import Db, DbPathConfig, Sql

config = DbPathConfig(
    database=Path("mydb.sqlite"),
    sql_templates_dir=Path("sql/"),
)

with Db.from_config(config) as db:
    # Loads query from sql/get_user_by_id.sql
    user = db.fetchone(Sql.template("get_user_by_id.sql"), (1,))
```

Or specify the template path directly:

```python
with Db("mydb.sqlite") as db:
    sql = Sql.template("get_user_by_id.sql", path=Path("sql/"))
    user = db.fetchone(sql, (1,))
```

### Autocommit Mode

Disable transaction management for auto-committing each statement:

```python
with Db("mydb.sqlite", autocommit=True) as db:
    db.execute(Sql.raw("UPDATE users SET name = ? WHERE id = ?"), ("Bob", 1))
```

### Batch Operations

Execute multiple parameter sets or run SQL scripts:

```python
with Db("mydb.sqlite", autocommit=True) as db:
    # Execute same query with multiple parameter sets
    users = [("Alice",), ("Bob",), ("Charlie",)]
    db.executemany(Sql.raw("INSERT INTO users (name) VALUES (?)"), users)

    # Execute multiple statements as a script
    db.executescript(Sql.raw("""
        DELETE FROM users WHERE id = 1;
        UPDATE users SET name = 'Robert' WHERE name = 'Bob';
    """))
```

## API Reference

### Sql

| Method | Description |
|--------|-------------|
| `Sql.raw(query)` | Create a Sql instance from an inline query string |
| `Sql.template(filename, path=None)` | Create a Sql instance from a template file |

### Db

| Method | Description |
|--------|-------------|
| `Db(path, row_factory=None, sql_templates_dir=None, autocommit=False)` | Create a database connection |
| `Db.from_config(config, **kwargs)` | Create from a `DbPathConfig` |
| `execute(sql, *args)` | Execute a query and return the cursor |
| `executemany(sql, *args)` | Execute a query against multiple parameter sets |
| `executescript(sql)` | Execute multiple statements as a script |
| `fetchone(sql, *args)` | Execute and return the first row |
| `fetchall(sql, *args)` | Execute and return all rows |
| `commit(sql, *args)` | Execute and commit the transaction |

### Row Factories

| Factory | Description |
|---------|-------------|
| `dict_factory` | Return rows as dictionaries |
| `namedtuple_factory` | Return rows as namedtuples |

## More Examples

See the [test suite](https://github.com/smallwat3r/sqlitey/blob/main/tests/test_sqlitey.py) for more examples.
