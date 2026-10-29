import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from dotenv import load_dotenv

load_dotenv()

from config import database_url
from models import db

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prefer DATABASE_URL env var; fallback to app config. Read the config directly
# rather than building the app: migrations need only the database URL, not the
# app's secrets.
db_url = database_url()
target_metadata = db.metadata


def run_migrations_offline():
    url = db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(db_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
