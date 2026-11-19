from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


def open_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


def initialize_schema(connection: sqlite3.Connection, schema: str) -> None:
    if connection.in_transaction:
        raise sqlite3.ProgrammingError('schema initialization requires an idle connection')
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.executescript('BEGIN IMMEDIATE;\n' + schema + '\nCOMMIT;')
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
