"""Тесты слоя данных: репозиторий (повышенная сложность № 10).

Фикстура repository параметризована, поэтому каждый тест выполняется
для всех реализаций: в памяти, SQLite в памяти и SQLite в файле.
Так проверяется, что реализации взаимозаменяемы.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from currency_cli.data import RateRepository, SqliteRateRepository
from fakes import (FRIDAY, SATURDAY, SUNDAY, friday_table, make_table,
                   saturday_table)

FETCHED = datetime(2026, 10, 10, 12, 0)


def test_implements_interface(repository):
    """Любая реализация — это RateRepository."""
    assert isinstance(repository, RateRepository)


def test_empty(repository):
    """Пустое хранилище ничего не находит."""
    assert repository.get(SATURDAY) is None
    assert repository.latest() is None
    assert repository.days() == []
    assert repository.history("USD") == []


def test_save_and_get(repository):
    """Сохранённая таблица читается без изменений."""
    repository.save(saturday_table())
    assert repository.get(SATURDAY) == saturday_table()
    assert repository.get(FRIDAY) is None


def test_decimal_precision(repository):
    """Курсы хранятся без потери точности."""
    table = make_table(SATURDAY, USD=("0.000012345678", None))
    repository.save(table)
    assert repository.get(SATURDAY).get("USD").value == \
        Decimal("0.000012345678")
    assert repository.get(SATURDAY).get("USD").previous is None


def test_alias(repository):
    """Псевдоним даты ведёт к таблице другой даты."""
    repository.save(saturday_table())
    repository.alias(SUNDAY, SATURDAY)
    assert repository.get(SUNDAY) == saturday_table()
    repository.alias(SATURDAY, SATURDAY)
    assert repository.get(SATURDAY) == saturday_table()


def test_alias_to_missing_day(repository):
    """Псевдоним на несохранённую дату — ошибка."""
    with pytest.raises(KeyError):
        repository.alias(SUNDAY, SATURDAY)


def test_latest_and_fetched_at(repository):
    """Самая свежая таблица; время загрузки только у текущих курсов."""
    repository.save(friday_table(), fetched_at=FETCHED)
    repository.save(saturday_table())
    table, fetched_at = repository.latest()
    assert table.day == SATURDAY and fetched_at is None
    repository.save(saturday_table(), fetched_at=FETCHED)
    assert repository.latest()[1] == FETCHED


def test_resave_keeps_fetched_at_and_aliases(repository):
    """Повторное сохранение обновляет курсы, но не теряет метаданные."""
    repository.save(saturday_table(), fetched_at=FETCHED)
    repository.alias(SUNDAY, SATURDAY)
    updated = make_table(SATURDAY, USD=("90", "84.9048"))
    repository.save(updated)
    assert repository.get(SUNDAY) == updated
    assert repository.latest() == (updated, FETCHED)


def test_history(repository):
    """История: курсы одной валюты, новые сначала, не больше limit."""
    repository.save(friday_table())
    repository.save(saturday_table())
    history = repository.history("USD")
    assert [(day, rate.value) for day, rate in history] == [
        (SATURDAY, Decimal("84.9048")), (FRIDAY, Decimal("85.4173"))]
    assert len(repository.history("USD", limit=1)) == 1
    assert repository.history("XYZ") == []
    assert repository.days() == [FRIDAY, SATURDAY]


def test_sqlite_file_persists(tmp_path):
    """Данные в файле SQLite сохраняются после закрытия."""
    path = tmp_path / "rates.db"
    first = SqliteRateRepository(path)
    first.save(saturday_table(), fetched_at=FETCHED)
    first.alias(SUNDAY, SATURDAY)
    first.close()
    second = SqliteRateRepository(path)
    assert second.get(SUNDAY) == saturday_table()
    assert second.latest() == (saturday_table(), FETCHED)
    second.close()


def test_own_table_wins_over_alias(repository):
    """Если на дату появилась своя таблица, псевдоним больше не нужен."""
    repository.save(friday_table())
    repository.alias(SATURDAY, FRIDAY)
    repository.save(saturday_table())
    assert repository.get(SATURDAY) == saturday_table()
