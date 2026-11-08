"""Клиент API курсов ЦБ РФ на библиотеке requests.

Источник — https://www.cbr-xml-daily.ru (курсы ЦБ в формате JSON):
- текущие курсы:  /daily_json.js
- архив на дату:  /archive/ГГГГ/ММ/ДД/daily_json.js
  (в выходные и праздники ЦБ курсы не устанавливает — ответ 404).
"""

import logging
from datetime import date
from decimal import Decimal

import requests

from currency_cli.models import Rate, RateTable

BASE_URL = "https://www.cbr-xml-daily.ru"
TIMEOUT = 10

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Не удалось получить курсы от API."""


class NotPublished(ApiError):
    """ЦБ не публиковал курсы на эту дату (выходной или праздник)."""


def parse_table(data):
    """Преобразовать JSON ответа API в RateTable."""
    try:
        day = date.fromisoformat(data["Date"][:10])
        rates = {
            code: Rate(code=code, name=item["Name"],
                       nominal=int(item["Nominal"]),
                       value=Decimal(str(item["Value"])),
                       previous=Decimal(str(item["Previous"])))
            for code, item in data["Valute"].items()
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ApiError(f"Неожиданный формат ответа API: {error!r}") from None
    return RateTable(day, rates)


class CbrClient:
    """Получение таблиц курсов по HTTP.

    Сессию requests можно передать снаружи — так в тестах её заменяют
    подделкой и не ходят в сеть.
    """

    def __init__(self, session=None, base_url=BASE_URL, timeout=TIMEOUT):
        """Запомнить сессию, адрес API и таймаут запросов."""
        self.session = session if session is not None else requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def url_for(self, day=None):
        """Адрес JSON с курсами: текущими (day=None) или на дату."""
        if day is None:
            return f"{self.base_url}/daily_json.js"
        return (f"{self.base_url}/archive/"
                f"{day.year:04d}/{day.month:02d}/{day.day:02d}/daily_json.js")

    def fetch(self, day=None):
        """Загрузить таблицу курсов на дату day (None — текущие)."""
        url = self.url_for(day)
        log.info("Запрос курсов: %s", url)
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as error:
            raise ApiError(f"Нет связи с {self.base_url}: "
                           f"{type(error).__name__}") from error
        if response.status_code == 404 and day is not None:
            raise NotPublished(f"ЦБ не устанавливал курсы на {day}")
        try:
            response.raise_for_status()
            data = response.json(parse_float=Decimal)
        except requests.HTTPError as error:
            raise ApiError(f"Ошибка API: HTTP {response.status_code}") \
                from error
        except ValueError as error:
            raise ApiError("API вернул не JSON") from error
        return parse_table(data)
