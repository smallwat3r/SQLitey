# SQLight

Still a WIP...

Useful wrappers around `sqlite3`.

``` python
from sqlight import Db, DbConfig, Sql, namedtuple_factory

dir = Path(__file__).resolve().parent

config = DbConfig(
    db_file=dir / "db.sqlite3"
    sql_templates_dir=dir / "sql"
)

with Db(config, row_factory=namedtuple_factory) as db:
    result = db.fetchone(Sql.template("get_user_by_id.sql"), (3,))
    print(result.id, result.name)

ith Db(config) as db:
    db.commit(Sql.raw("INSERT INTO users VALUES (10, 'John');"))
```
