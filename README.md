# SQLight

Still a WIP...

SQLite nano framework.

``` python
from sqlight import Db, DbConfig, Sql, namedtuple_factory

dir = Path(__file__).resolve().parent

config = DbConfig(
    database=dir / "db.sqlite3"
    sql_templates_dir=dir / "sql"
)

with Db.from_config(config, row_factory=namedtuple_factory) as db:
    result = db.fetchone(Sql.template("get_user_by_id.sql"), (3,))
    print(result.id, result.name)

with Db.from_config(config, timeout=15) as db:
    db.commit(Sql.raw("INSERT INTO users VALUES (10, 'John');"))

with Db("db.sqlite3", autocommit=True) as db:
    db.execute(Sql.raw("UPDATE users SET name = 'Johnny' WHERE id = 10;"))
```
