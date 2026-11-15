# SQLitey

A small, typed wrapper around Python's built-in `sqlite3`. It keeps you writing plain SQL, and takes care of the repetitive parts: connections, transactions, row shapes, SQL files and migrations.

- **No dependencies**, standard library only
- **Plain SQL**, inline or loaded from `.sql` files
- **Rows the way you want them**: tuples, dicts, namedtuples or your own dataclasses
- **Safe transactions**: commit on success, roll back on error, nestable atomic blocks
- **Migrations built in**, from numbered `.sql` files
- **Fully typed**, ships with type hints

Requires Python 3.11 or newer.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Guide](#guide)
  - [Writing queries](#writing-queries)
  - [Reading results](#reading-results)
  - [Row factories](#row-factories)
  - [SQL files](#sql-files)
  - [Transactions](#transactions)
  - [Bulk inserts and scripts](#bulk-inserts-and-scripts)
  - [Pragmas](#pragmas)
  - [Read-only access](#read-only-access)
  - [Migrations](#migrations)
- [Things to know](#things-to-know)
- [API reference](#api-reference)
- [Development](#development)

## Installation

```
pip install sqlitey
```

## Quick start

```python
from dataclasses import dataclass

from sqlitey import Db, Sql, dataclass_factory


@dataclass
class User:
    id: int
    name: str


with Db(":memory:") as db:
    db.execute(Sql.raw("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"))
    db.execute(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Alice",))

    user = db.fetchone(
        Sql.raw("SELECT id, name FROM users WHERE name = ?"),
        ("Alice",),
        row_factory=dataclass_factory(User),
    )
    print(user)  # User(id=1, name='Alice')
```

When the `with` block ends, your changes are committed and the connection is closed. If an exception is raised inside the block, the changes are rolled back instead. Use a file path such as `"app.db"` instead of `":memory:"` to keep the data.

Queries can also live in their own `.sql` files, and be referred to by filename:

```sql
-- sql/get_user_by_name.sql
SELECT id, name FROM users WHERE name = ?
```

```python
from pathlib import Path

with Db("app.db", sql_templates_dir=Path("sql")) as db:
    user = db.fetchone(Sql.template("get_user_by_name.sql"), ("Alice",))
```

## Guide

### Writing queries

Every query is wrapped in a `Sql` object. Use `Sql.raw()` for inline SQL:

```python
get_user = Sql.raw("SELECT id, name FROM users WHERE id = ?")
```

Pass values separately, as parameters. Both positional (`?`) and named (`:name`) placeholders work:

```python
db.fetchone(Sql.raw("SELECT * FROM users WHERE id = ?"), (1,))
db.fetchone(Sql.raw("SELECT * FROM users WHERE id = :id"), {"id": 1})
```

Never build a query by formatting values into the string, that is how SQL injection happens:

```python
# Don't do this
db.fetchone(Sql.raw(f"SELECT * FROM users WHERE name = '{name}'"))

# Do this
db.fetchone(Sql.raw("SELECT * FROM users WHERE name = ?"), (name,))
```

To help with that, `Sql.raw()` is typed as `LiteralString`. Type checkers that enforce it, such as pyright, report the first example above as an error. Note this is a static check only, nothing is verified at runtime.

### Reading results

| You want | Use | Returns |
|----------|-----|---------|
| One row | `db.fetchone(sql, params)` | A row, or `None` |
| All rows | `db.fetchall(sql, params)` | A list of rows |
| A single value | `db.fetchval(sql, params)` | The first column of the first row, or `None` |
| To loop over many rows | `db.execute(sql, params)` | A cursor you can iterate |

```python
total = db.fetchval(Sql.raw("SELECT COUNT(*) FROM users"))  # 2

for user_id, name in db.execute(Sql.raw("SELECT id, name FROM users")):
    print(user_id, name)
```

### Row factories

By default rows are tuples. Pass a `row_factory` to get something friendlier.

As dictionaries:

```python
from sqlitey import Db, Sql, dict_factory

with Db("app.db", row_factory=dict_factory) as db:
    user = db.fetchone(Sql.raw("SELECT id, name FROM users WHERE id = ?"), (1,))
    print(user["name"])  # 'Alice'
```

As namedtuples:

```python
from sqlitey import Db, Sql, namedtuple_factory

with Db("app.db", row_factory=namedtuple_factory) as db:
    user = db.fetchone(Sql.raw("SELECT id, name FROM users WHERE id = ?"), (1,))
    print(user.name)  # 'Alice'
```

As your own classes, the column names must match the field names. A class fits one shape of row, so pass the factory to the query rather than to `Db`:

```python
from dataclasses import dataclass
from sqlitey import Db, Sql, dataclass_factory

@dataclass
class User:
    id: int
    name: str

@dataclass
class Order:
    id: int
    total: float

with Db("app.db") as db:
    user = db.fetchone(
        Sql.raw("SELECT id, name FROM users WHERE id = ?"),
        (1,),
        row_factory=dataclass_factory(User),
    )
    print(user)  # User(id=1, name='Alice')

    orders = db.fetchall(
        Sql.raw("SELECT id, total FROM orders"),
        row_factory=dataclass_factory(Order),
    )
```

`execute`, `fetchone` and `fetchall` all accept `row_factory`, with any factory. It applies to that query only and takes precedence over the one given to `Db`.

Row types follow the factory for type checkers too. `user` above is typed as `User | None`, and without a per query factory, rows are typed from the one given to `Db`: tuples by default, `dict[str, Any]` with `dict_factory`.

> **Tip:** with `namedtuple_factory`, a column such as `COUNT(*)` is not a valid attribute name, so it is renamed to its position (`_0`, `_1`, ...). Give it an alias to get a proper name: `SELECT COUNT(*) AS total`.

### SQL files

Longer queries are easier to read, and to syntax-highlight, in their own `.sql` files. Point `Db` at the directory and refer to queries by filename:

```
sql/
  get_user_by_id.sql
  list_users.sql
```

```python
from pathlib import Path
from sqlitey import Db, Sql

with Db("app.db", sql_templates_dir=Path("sql")) as db:
    user = db.fetchone(Sql.template("get_user_by_id.sql"), (1,))
```

A single query can also carry its own directory:

```python
sql = Sql.template("get_user_by_id.sql", path=Path("sql"))
```

If you pass the database and the SQL directory around together, `DbPathConfig` bundles them:

```python
from sqlitey import Db, DbPathConfig

config = DbPathConfig(database=Path("app.db"), sql_templates_dir=Path("sql"))

with Db.from_config(config) as db:
    ...
```

`Sql` objects are immutable, so you can define them once at the top of a module and reuse them everywhere.

### Transactions

Inside a `with Db(...)` block, your changes form one transaction:

- the block ends normally, everything is **committed**
- the block raises an exception, everything is **rolled back**

For finer control, wrap a group of statements in `db.transaction()`. They succeed or fail together, without affecting the rest of your work:

```python
with Db("app.db") as db:
    db.execute(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Alice",))

    try:
        with db.transaction():
            db.execute(Sql.raw("INSERT INTO users (name) VALUES (?)"), ("Bob",))
            raise RuntimeError("something went wrong")
    except RuntimeError:
        pass  # Bob is rolled back, Alice is kept
```

`db.transaction()` blocks can be nested. When no transaction is open yet, the outermost block commits as soon as it succeeds.

Other options:

- `db.commit(sql, params)` runs a statement and commits straight away
- `Db("app.db", autocommit=True)` commits every statement as it runs
- without a `with` block, call `db.close()` yourself when done. Uncommitted changes are discarded, so commit first

`db.commit()` and `db.executescript()` both commit, so they raise `RuntimeError` inside a `db.transaction()` block, where that would break the all-or-nothing guarantee.

### Bulk inserts and scripts

Run one statement with many sets of parameters:

```python
users = [("Alice",), ("Bob",), ("Charlie",)]
db.executemany(Sql.raw("INSERT INTO users (name) VALUES (?)"), users)
```

Run several statements at once:

```python
db.executescript(Sql.raw("""
    DELETE FROM users WHERE id = 1;
    UPDATE users SET name = 'Robert' WHERE name = 'Bob';
"""))
```

### Pragmas

SQLite's defaults are conservative, most notably **foreign keys are not enforced** unless you ask. `RECOMMENDED_PRAGMAS` turns on the settings most applications want: foreign keys, WAL journalling (readers do not block the writer) and `synchronous = normal`.

```python
from sqlitey import Db, RECOMMENDED_PRAGMAS

with Db("app.db", pragmas=RECOMMENDED_PRAGMAS) as db:
    ...
```

Or choose your own:

```python
with Db("app.db", pragmas={"foreign_keys": True, "cache_size": -8000}) as db:
    ...
```

### Read-only access

Open an existing database with `readonly=True` when you only mean to read it, for reports or scripts for example. Any write raises `sqlite3.OperationalError`, and a missing file is an error instead of being created:

```python
with Db("app.db", readonly=True) as db:
    total = db.fetchval(Sql.raw("SELECT COUNT(*) FROM users"))
```

### Migrations

Keep your schema changes as numbered `.sql` files, named `<version>_<description>.sql`:

```
migrations/
  001_create_users.sql
  002_add_email.sql
```

Then call `migrate` when your application starts:

```python
from pathlib import Path
from sqlitey import Db

with Db("app.db") as db:
    applied = db.migrate(Path("migrations"))
    print(f"{applied} migration(s) applied")
```

- Only files newer than the database's current version are run, in order. The version is stored in the database itself (`PRAGMA user_version`), so no extra table is needed.
- Each file is all-or-nothing. If one fails, the database stays at the previous version and the error is raised.
- It is safe to call from several processes at once, each file is applied only once.

To add a change later, add a new file with the next number. Never edit a migration that has already been applied.

## Things to know

- **No committing inside a `db.transaction()` block.** `db.commit()` and `db.executescript()` raise `RuntimeError` there. Avoid `db.conn.commit()` in a block too, it cannot be guarded.
- **`db.migrate()` needs a clean slate.** It raises `RuntimeError` if you have uncommitted changes, call it first.
- **Migration files must not contain `BEGIN` or `COMMIT`.** Each file already runs in its own transaction.
- **SQL files are cached.** A file is read once per process, restart to pick up edits.
- **Need something not covered here?** The underlying `sqlite3` connection is available as `db.conn`.

## API reference

### Sql

| Method | Description |
|--------|-------------|
| `Sql.raw(query)` | A query from an inline string |
| `Sql.template(filename, path=None)` | A query loaded from a `.sql` file |

### Db

| Method | Description |
|--------|-------------|
| `Db(database, row_factory=None, sql_templates_dir=None, autocommit=False, pragmas=None, readonly=False)` | Open a database. Extra arguments are passed to `sqlite3.connect()` |
| `Db.from_config(config, **kwargs)` | Open a database from a `DbPathConfig` |
| `execute(sql, params=(), row_factory=None)` | Run a query and return a cursor |
| `executemany(sql, seq_of_params)` | Run a query once per set of parameters |
| `executescript(sql)` | Run several statements as a script |
| `fetchone(sql, params=(), row_factory=None)` | Run a query and return the first row, or `None` |
| `fetchall(sql, params=(), row_factory=None)` | Run a query and return all rows |
| `fetchval(sql, params=())` | Run a query and return the first column of the first row, or `None` |
| `commit(sql, params=())` | Run a query and commit |
| `transaction()` | Context manager, runs a block atomically, nestable |
| `migrate(directory)` | Apply pending migration files, return how many ran |
| `close()` | Close the connection, discarding uncommitted changes |
| `conn` | The underlying `sqlite3.Connection` |

### Row factories

| Factory | Rows are returned as |
|---------|----------------------|
| *(none)* | Tuples |
| `dict_factory` | Dictionaries |
| `namedtuple_factory` | Namedtuples |
| `dataclass_factory(cls)` | Instances of `cls` |

### Other

| Name | Description |
|------|-------------|
| `DbPathConfig(database, sql_templates_dir=None)` | Bundles a database path and a SQL directory |
| `RECOMMENDED_PRAGMAS` | Foreign keys on, WAL journalling, `synchronous = normal` |

## Development

The project uses [uv](https://docs.astral.sh/uv/).

```
make deps    # install dependencies
make tests   # run the test suite
make ruff    # lint
make fmt     # format
make mypy    # type check
```

The [test suite](https://github.com/smallwat3r/sqlitey/blob/main/tests/test_sqlitey.py) doubles as a set of runnable examples.

## Licence

MIT, see [LICENSE](LICENSE).
