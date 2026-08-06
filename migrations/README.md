# Database migrations

M1-A initializes Alembic for the main application database. The first revision creates:

- connector definitions and instances;
- platform accounts;
- connector runs and checkpoints;
- platform risk events.

Alembic reads `DATABASE_URL` through application `Settings`; credentials are never stored in
`alembic.ini`. Application tables must not be created manually in `docker/postgres/init.sql`; that
file remains limited to database extensions.

```bash
alembic upgrade head
alembic downgrade base
alembic upgrade head
```
