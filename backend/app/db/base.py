from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Give every constraint an explicit name. Without this SQLAlchemy invents
# anonymous names, and a later Alembic downgrade cannot drop a constraint
# it cannot name.
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)


class Base(DeclarativeBase):
    """Every model inherits this, so they all end up in one metadata."""

    metadata = metadata