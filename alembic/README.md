Use Alembic for schema migrations.

Common commands:
- `alembic revision --autogenerate -m "message"`
- `alembic upgrade head`
- `alembic downgrade -1`

Ensure DATABASE_URL is set (env) before running.