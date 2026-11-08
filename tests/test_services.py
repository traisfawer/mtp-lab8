"""Тесты слоя сервисов (повышенная сложность № 10).

Слой сервисов проверяется отдельно от сети и SQLite: ему передаются
поддельный клиент и репозиторий в памяти.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

import pytest

from currency_cli.data import ApiError, InMemoryRateRepository
from currency_cli.services import RateService, ServiceError, UnknownCurrency
from fakes import FRIDAY, SATURDAY, SUNDAY, FakeClient, friday_table


def test_current_rates_cached_for_today(service, client):
    """Текущие курсы загружаются один раз за день."""
    assert service.get_rates().day == SATURDAY
    assert service.get_rates().day == SATURDAY
    assert client.calls == [None]


def test_current_rates_refresh(service, client):
    """refresh=True загружает курсы заново."""
    service.get_rates()
    service.get_rates(refresh=True)
    assert client.calls == [None, None]


def test_current_rates_reloaded_next_day(service, client, clock):
    """На следующий день текущие курсы запрашиваются снова."""
    service.get_rates()
    clock.now += timedelta(days=1)
    service.get_rates()
    assert client.calls == [None, None]


def test_archive_table_is_not_current(service, client):
    """Архивная таблица в кэше не считается текущими курсами."""
    service.get_rates(SATURDAY)
    service.get_rates()
    assert client.calls == [SATURDAY, None]


def test_offline_uses_cache(service, client, caplog):
    """Без сети возвращаются сохранённые курсы с предупреждением."""
    service.get_rates()
    client.error = ApiError("Нет связи с API")
    with caplog.at_level(logging.WARNING):
        table = service.get_rates(refresh=True)
    assert table.day == SATURDAY
    assert "Нет связи с API" in caplog.text


def test_offline_without_cache(clock):
    """Без сети и без кэша — понятная ошибка."""
    service = RateService(InMemoryRateRepository(),
                          FakeClient(error=ApiError("Нет связи")), clock)
    with pytest.raises(ServiceError, match="Нет связи"):
        service.get_rates()


def test_rates_on_date(service, client):
    """Курсы на дату загружаются из архива и кэшируются."""
    assert service.get_rates(FRIDAY) == friday_table()
    assert service.get_rates(FRIDAY) == friday_table()
    assert client.calls == [FRIDAY]


def test_weekend_uses_previous_rates(service, client):
    """В воскресенье действуют курсы, установленные в субботу."""
    assert service.get_rates(SUNDAY).day == SATURDAY
    assert client.calls == [SUNDAY, SATURDAY]
    assert service.get_rates(SUNDAY).day == SATURDAY
    assert client.calls == [SUNDAY, SATURDAY]


def test_weekend_uses_cached_previous_day(service, client):
    """Если суббота уже в кэше, к API обращаются только за воскресеньем."""
    service.get_rates(SATURDAY)
    service.get_rates(SUNDAY)
    assert client.calls == [SATURDAY, SUNDAY]


def test_lookback_limit(clock):
    """Если курсов нет слишком долго — ошибка, а не бесконечный поиск."""
    client = FakeClient()
    service = RateService(InMemoryRateRepository(), client, clock,
                          max_lookback=3)
    with pytest.raises(ServiceError, match="Не найдено курсов за 3"):
        service.get_rates(SUNDAY)
    assert len(client.calls) == 4


def test_date_api_error(service, client):
    """Сбой API при запросе архива — ServiceError."""
    client.error = ApiError("HTTP 500")
    with pytest.raises(ServiceError, match="HTTP 500"):
        service.get_rates(FRIDAY)


def test_future_date(service):
    """Курсов на дату позже завтрашней ещё нет."""
    with pytest.raises(ServiceError, match="ещё не установлены"):
        service.get_rates(SUNDAY + timedelta(days=2))


@pytest.mark.parametrize("amount, source, target, result, rate", [
    ("100", "USD", "RUB", "8490.48", "84.9048"),
    ("8490.48", "RUB", "USD", "100.00", None),
    ("100", "usd", "eur", "89.40", None),
    ("1000", "JPY", "RUB", "537.03", "0.537032"),
    ("1000", "KZT", "JPY", "352.16", None),
    ("50", "EUR", "EUR", "50.00", "1"),
])
def test_convert(service, amount, source, target, result, rate):
    """Пересчёт через рубль с учётом номинала и округлением до копеек."""
    conversion = service.convert(Decimal(amount), source, target)
    assert conversion.result == Decimal(result)
    assert (conversion.source, conversion.target) == (source.upper(),
                                                      target.upper())
    assert conversion.day == SATURDAY
    if rate is not None:
        assert conversion.rate == Decimal(rate)


def test_convert_rounding_half_up(service):
    """Половина копейки округляется вверх (ROUND_HALF_UP)."""
    assert service.convert(Decimal("0.125"), "RUB", "RUB").result == \
        Decimal("0.13")


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_convert_bad_amount(service, amount):
    """Сумма должна быть положительной."""
    with pytest.raises(ServiceError, match="больше нуля"):
        service.convert(Decimal(amount), "USD")


def test_convert_unknown_currency(service):
    """Неизвестная валюта — ошибка со списком доступных."""
    with pytest.raises(UnknownCurrency, match="Доступны: RUB, EUR"):
        service.convert(Decimal(1), "XYZ")


def test_convert_on_date(service):
    """Пересчёт по курсу на дату."""
    assert service.convert(Decimal(1), "USD", day=FRIDAY).result == \
        Decimal("85.42")


def test_history(service, client):
    """История за 3 дня: суббота и воскресенье дают одну дату."""
    history = service.history("USD", days=3)
    assert [day for day, _ in history] == [FRIDAY, SATURDAY]
    assert history[-1][1].value == Decimal("84.9048")


@pytest.mark.parametrize("days", [0, 32])
def test_history_bad_days(service, days):
    """Число дней ограничено."""
    with pytest.raises(ServiceError):
        service.history("USD", days=days)


def test_top_changes(service):
    """Валюты упорядочены по модулю изменения за день."""
    table, rates = service.top_changes(2)
    assert table.day == SATURDAY
    assert [rate.code for rate in rates] == ["KZT", "JPY"]


def test_today_from_clock(service):
    """Дата сервиса берётся из переданных часов."""
    assert service.today() == date(2026, 10, 11)
