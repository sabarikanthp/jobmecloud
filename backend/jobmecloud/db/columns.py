"""Key columns that work on SQLite (tests) and Aurora DSQL.

DSQL has no SERIAL: identity columns must be bigint with an explicit CACHE. SQLite needs a plain
INTEGER primary key to auto-number, so the bigint type falls back to INTEGER there.
"""

from sqlalchemy import BigInteger, Column, ForeignKey, Identity, Integer
from sqlmodel import Field

ID_CACHE = 100


def _id_type():
    return BigInteger().with_variant(Integer(), "sqlite")


def pk_column():
    return Field(default=None, sa_column=Column(_id_type(), Identity(always=False, cache=ID_CACHE), primary_key=True))


def fk(target: str, *, optional: bool = False):
    column = Column(_id_type(), ForeignKey(target), nullable=optional)
    return Field(default=None, sa_column=column) if optional else Field(sa_column=column)
