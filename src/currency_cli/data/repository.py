"""Хранилище курсов по шаблону «Репозиторий» (Repository).

RateRepository задаёт интерфейс хранилища, а слой сервисов работает
только с этим интерфейсом. Поэтому реализации взаимозаменяемы:
- SqliteRateRepository — постоянное хранение в файле SQLite;
- InMemoryRateRepository — хранение в памяти (для тестов и отладки).

Кроме самих таблиц хранятся:
- «псевдонимы» дат: курсы на воскресенье — это курсы, установленные
  в субботу, и при повторном запросе воскресенья API не нужен;
- время загрузки (fetched_at) — только у таблиц, полученных как
  текущие курсы; у архивных таблиц оно равно None.
"""

import sqlite3
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal

from currency_cli.models import Rate, RateTable


class RateRepository(ABC):
    """Интерфейс хранилища таблиц курсов."""

    @abstractmethod
    def save(self, table, fetched_at=None):
        """Сохранить таблицу (fetched_at — время загрузки текущих курсов)."""

    @abstractmethod
    def alias(self, requested, day):
        """Запомнить, что на дату requested действуют курсы от day."""

    @abstractmethod
    def get(self, day):
        """Таблица на дату day (с учётом псевдонимов) или None."""

    @abstractmethod
    def latest(self):
        """Пара (самая свежая таблица, fetched_at или None) или None."""

    @abstractmethod
    def history(self, code, limit=10):
        """Последние limit курсов валюты: список пар (дата, Rate)."""

    @abstractmethod
    def days(self):
        """Даты всех сохранённых таблиц по возрастанию."""


class InMemoryRateRepository(RateRepository):
    """Хранилище в памяти процесса."""

    def __init__(self):
        """Создать пустое хранилище."""
        self._tables = {}
        self._fetched = {}
        self._aliases = {}

    def save(self, table, fetched_at=None):
        """Сохранить таблицу (fetched_at — время загрузки текущих курсов)."""
        self._tables[table.day] = table
        if fetched_at is not None or table.day not in self._fetched:
            self._fetched[table.day] = fetched_at

    def alias(self, requested, day):
        """Запомнить, что на дату requested действуют курсы от day."""
        if day not in self._tables:
            raise KeyError(f"Нет таблицы курсов на {day}")
        if requested != day:
            self._aliases[requested] = day

    def get(self, day):
        """Таблица на дату day (с учётом псевдонимов) или None."""
        return self._tables.get(self._aliases.get(day, day))

    def latest(self):
        """Пара (самая свежая таблица, fetched_at или None) или None."""
        if not self._tables:
            return None
        day = max(self._tables)
        return self._tables[day], self._fetched[day]

    def history(self, code, limit=10):
        """Последние limit курсов валюты: список пар (дата, Rate)."""
        found = [(day, self._tables[day].rates[code])
                 for day in sorted(self._tables, reverse=True)
                 if code in self._tables[day].rates]
        return found[:limit]

    def days(self):
        """Даты всех сохранённых таблиц по возрастанию."""
        return sorted(self._tables)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tables (
    day        TEXT PRIMARY KEY,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS rates (
    day      TEXT    NOT NULL REFERENCES tables (day) ON DELETE CASCADE,
    code     TEXT    NOT NULL,
    name     TEXT    NOT NULL,
    nominal  INTEGER NOT NULL CHECK (nominal > 0),
    value    TEXT    NOT NULL,
    previous TEXT,
    PRIMARY KEY (day, code)
);
CREATE TABLE IF NOT EXISTS aliases (
    requested TEXT PRIMARY KEY,
    day       TEXT NOT NULL REFERENCES tables (day) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rates_code_day ON rates (code, day);
"""


class SqliteRateRepository(RateRepository):
    """Хранилище в базе SQLite.

    Курсы хранятся как TEXT, чтобы Decimal восстанавливался без потери
    точности (тип REAL в SQLite — это float).
    """

    def __init__(self, path=":memory:"):
        """Открыть (или создать) базу и таблицы."""
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self):
        """Закрыть соединение с базой."""
        self.conn.close()

    def save(self, table, fetched_at=None):
        """Сохранить таблицу (fetched_at — время загрузки текущих курсов).

        Повторное сохранение той же даты заменяет курсы, но не удаляет
        псевдонимы дат и не стирает уже известное время загрузки.
        """
        day = table.day.isoformat()
        fetched = (None if fetched_at is None
                   else fetched_at.isoformat(timespec="seconds"))
        with self.conn:
            self.conn.execute(
                "INSERT INTO tables (day, fetched_at) VALUES (?, ?) "
                "ON CONFLICT (day) DO UPDATE SET fetched_at = "
                "COALESCE(excluded.fetched_at, tables.fetched_at)",
                (day, fetched))
            self.conn.execute("DELETE FROM rates WHERE day = ?", (day,))
            self.conn.executemany(
                "INSERT INTO rates (day, code, name, nominal, value, "
                "previous) VALUES (?, ?, ?, ?, ?, ?)",
                [(day, r.code, r.name, r.nominal, str(r.value),
                  None if r.previous is None else str(r.previous))
                 for r in table.rates.values()])

    def alias(self, requested, day):
        """Запомнить, что на дату requested действуют курсы от day."""
        if requested == day:
            return
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO aliases (requested, day) "
                    "VALUES (?, ?)", (requested.isoformat(), day.isoformat()))
        except sqlite3.IntegrityError:
            raise KeyError(f"Нет таблицы курсов на {day}") from None

    def _load(self, day):
        """Прочитать таблицу на точную дату day (строка ISO)."""
        rows = self.conn.execute(
            "SELECT code, name, nominal, value, previous FROM rates "
            "WHERE day = ?", (day,)).fetchall()
        rates = {code: Rate(code, name, nominal, Decimal(value),
                            None if previous is None else Decimal(previous))
                 for code, name, nominal, value, previous in rows}
        return RateTable(date.fromisoformat(day), rates)

    def get(self, day):
        """Таблица на дату day (с учётом псевдонимов) или None."""
        row = self.conn.execute(
            "SELECT t.day FROM tables AS t WHERE t.day = :day "
            "UNION SELECT a.day FROM aliases AS a WHERE a.requested = :day",
            {"day": day.isoformat()}).fetchone()
        return None if row is None else self._load(row[0])

    def latest(self):
        """Пара (самая свежая таблица, fetched_at или None) или None."""
        row = self.conn.execute(
            "SELECT day, fetched_at FROM tables "
            "ORDER BY day DESC LIMIT 1").fetchone()
        if row is None:
            return None
        day, fetched = row
        return (self._load(day),
                None if fetched is None else datetime.fromisoformat(fetched))

    def history(self, code, limit=10):
        """Последние limit курсов валюты: список пар (дата, Rate)."""
        rows = self.conn.execute(
            "SELECT day, code, name, nominal, value, previous FROM rates "
            "WHERE code = ? ORDER BY day DESC LIMIT ?",
            (code, limit)).fetchall()
        return [(date.fromisoformat(day),
                 Rate(code, name, nominal, Decimal(value),
                      None if previous is None else Decimal(previous)))
                for day, code, name, nominal, value, previous in rows]

    def days(self):
        """Даты всех сохранённых таблиц по возрастанию."""
        return [date.fromisoformat(row[0]) for row in self.conn.execute(
            "SELECT day FROM tables ORDER BY day")]
