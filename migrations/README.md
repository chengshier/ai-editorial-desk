# Database migrations

Alembic migrations will be initialized in M1 together with the first persistent models:

- connector definitions and instances;
- platform accounts;
- connector runs and checkpoints;
- risk events and collection budgets.

Do not create application tables manually in `docker/postgres/init.sql`; that file is limited to database extensions.
