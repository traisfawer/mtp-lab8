"""Подделки и тестовые данные: тесты не обращаются к сети."""

import json
from datetime import date
from decimal import Decimal

import requests

from currency_cli.data import NotPublished
from currency_cli.models import Rate, RateTable

FRIDAY = date(2026, 10, 9)
SATURDAY = date(2026, 10, 10)
SUNDAY = date(2026, 10, 11)

NAMES = {"USD": "Доллар США", "EUR": "Евро", "JPY": "Иен",
         "KZT": "Тенге"}
NOMINALS = {"JPY": 100, "KZT": 100}


def make_table(day, **values):
    """Собрать таблицу курсов из пар (курс, вчерашний курс) по кодам."""
    rates = {}
    for code, (value, previous) in values.items():
        rates[code] = Rate(code, NAMES.get(code, code),
                           NOMINALS.get(code, 1), Decimal(value),
                           None if previous is None else Decimal(previous))
    return RateTable(day, rates)


def friday_table():
    """Курсы на пятницу 09.10.2026."""
    return make_table(FRIDAY, USD=("85.4173", "85.4811"),
                      EUR=("95.4709", "95.6120"),
                      JPY=("54.1061", "54.3000"),
                      KZT=("19.1030", "19.0000"))


def saturday_table():
    """Курсы на субботу 10.10.2026."""
    return make_table(SATURDAY, USD=("84.9048", "85.4173"),
                      EUR=("94.9745", "95.4709"),
                      JPY=("53.7032", "54.1061"),
                      KZT=("18.9123", "19.1030"))


def cbr_json(day="2026-10-10", **valute):
    """Собрать JSON в формате API из троек (номинал, курс, вчерашний)."""
    return {
        "Date": f"{day}T11:30:00+03:00",
        "PreviousDate": "2026-10-09T11:30:00+03:00",
        "Valute": {
            code: {"ID": f"R{code}", "CharCode": code, "Nominal": nominal,
                   "Name": NAMES.get(code, code), "Value": value,
                   "Previous": previous}
            for code, (nominal, value, previous) in valute.items()
        },
    }


def make_response(status=200, payload=None, text=None):
    """Настоящий requests.Response с заданным кодом и телом."""
    response = requests.Response()
    response.status_code = status
    body = text if text is not None else json.dumps(payload)
    response._content = body.encode("utf-8")
    response.encoding = "utf-8"
    return response


class FakeSession:
    """Подделка requests.Session: отдаёт заготовленный ответ."""

    def __init__(self, response=None, error=None):
        """Запомнить ответ или исключение, которое нужно выдать."""
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, timeout=None):
        """Записать запрос и вернуть ответ (или бросить исключение)."""
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    """Подделка CbrClient: таблицы по датам и текущая таблица."""

    def __init__(self, tables=(), current=None, error=None):
        """Задать архивные таблицы, текущую таблицу и ошибку связи."""
        self.tables = {table.day: table for table in tables}
        self.current = current
        self.error = error
        self.calls = []

    def fetch(self, day=None):
        """Вернуть таблицу как настоящий клиент (без сети)."""
        self.calls.append(day)
        if self.error is not None:
            raise self.error
        if day is None:
            return self.current
        if day not in self.tables:
            raise NotPublished(f"Нет курсов на {day}")
        return self.tables[day]
