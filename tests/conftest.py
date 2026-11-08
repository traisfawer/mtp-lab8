"""Общие фикстуры pytest."""

from datetime import datetime

import pytest

from currency_cli.data import InMemoryRateRepository, SqliteRateRepository
from currency_cli.services import RateService
from fakes import FakeClient, friday_table, saturday_table

NOW = datetime(2026, 10, 11, 15, 0)


@pytest.fixture(params=["memory", "sqlite-memory", "sqlite-file"])
def repository(request, tmp_path):
    """Каждая реализация репозитория — один и тот же набор тестов."""
    if request.param == "memory":
        yield InMemoryRateRepository()
        return
    path = ":memory:" if request.param == "sqlite-memory" \
        else tmp_path / "rates.db"
    repo = SqliteRateRepository(path)
    yield repo
    repo.close()


@pytest.fixture
def client():
    """Поддельный клиент: курсы на пятницу и субботу, текущие — суббота."""
    return FakeClient([friday_table(), saturday_table()],
                      current=saturday_table())


@pytest.fixture
def clock():
    """Изменяемые часы сервиса: clock.now можно сдвигать в тесте."""
    class Clock:
        now = NOW

        def __call__(self):
            return self.now

    return Clock()


@pytest.fixture
def service(client, clock):
    """Сервис с репозиторием в памяти и поддельным клиентом."""
    return RateService(InMemoryRateRepository(), client, clock=clock)
