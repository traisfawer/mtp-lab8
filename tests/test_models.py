"""Тесты модели предметной области."""

from decimal import Decimal

from currency_cli.models import RUBLE, Rate
from fakes import SATURDAY, saturday_table


def test_per_unit_uses_nominal():
    """Курс за единицу делится на номинал (100 иен)."""
    jpy = saturday_table().get("JPY")
    assert jpy.per_unit == Decimal("0.537032")


def test_change_and_percent():
    """Изменение за день в рублях и процентах."""
    usd = saturday_table().get("USD")
    assert usd.change == Decimal("-0.5125")
    assert round(usd.change_percent, 2) == Decimal("-0.60")


def test_change_without_previous():
    """Без вчерашнего курса изменение неизвестно."""
    rate = Rate("USD", "Доллар США", 1, Decimal("80"))
    assert rate.change is None and rate.change_percent is None


def test_table_get():
    """Поиск без учёта регистра; рубль есть в любой таблице."""
    table = saturday_table()
    assert table.get("usd").code == "USD"
    assert table.get("RUB") is RUBLE
    assert table.get("XYZ") is None
    assert table.codes() == ["EUR", "JPY", "KZT", "USD"]
    assert table.day == SATURDAY
