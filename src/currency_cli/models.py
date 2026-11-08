"""Модель предметной области: курс валюты и таблица курсов на дату.

Денежные значения хранятся в Decimal, а не во float, чтобы не терять
точность при пересчёте (0.1 + 0.2 != 0.3 для float).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

BASE_CURRENCY = "RUB"


@dataclass(frozen=True)
class Rate:
    """Официальный курс одной валюты.

    value — стоимость nominal единиц валюты в рублях
    (например, 100 японских иен = 53.7032 ₽).
    """

    code: str
    name: str
    nominal: int
    value: Decimal
    previous: Decimal | None = None

    @property
    def per_unit(self):
        """Стоимость одной единицы валюты в рублях."""
        return self.value / self.nominal

    @property
    def change(self):
        """Изменение курса за день (в рублях за nominal) или None."""
        if self.previous is None:
            return None
        return self.value - self.previous

    @property
    def change_percent(self):
        """Изменение курса за день в процентах или None."""
        if not self.previous:
            return None
        return self.change / self.previous * 100


RUBLE = Rate(BASE_CURRENCY, "Российский рубль", 1, Decimal(1), Decimal(1))


@dataclass(frozen=True)
class RateTable:
    """Курсы всех валют, установленные ЦБ РФ на дату day."""

    day: date
    rates: dict = field(default_factory=dict)

    def get(self, code):
        """Вернуть курс валюты по коду (RUB — всегда 1) или None."""
        code = code.upper()
        if code == BASE_CURRENCY:
            return RUBLE
        return self.rates.get(code)

    def codes(self):
        """Отсортированный список кодов валют таблицы."""
        return sorted(self.rates)
