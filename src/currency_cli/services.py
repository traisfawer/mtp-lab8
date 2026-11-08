"""Слой сервисов: бизнес-правила работы с курсами валют.

RateService получает курсы через клиент API и хранит их в репозитории.
Здесь, и только здесь, решается:
- брать курсы из кэша (репозитория) или запрашивать у API;
- что делать с выходными: курсы на воскресенье — это последние курсы,
  установленные до него (поиск назад не более чем на MAX_LOOKBACK дней);
- что делать без интернета: вернуть сохранённые курсы с предупреждением;
- как пересчитать сумму из одной валюты в другую (через рубль).

Слой сервисов не знает ни про HTTP, ни про SQL, ни про командную строку:
клиент и репозиторий передаются ему снаружи (внедрение зависимостей).
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from currency_cli.data.api_client import ApiError, NotPublished
from currency_cli.models import BASE_CURRENCY

MAX_LOOKBACK = 10
MAX_HISTORY_DAYS = 31
MAX_AMOUNT = Decimal("1e15")
CENT = Decimal("0.01")

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """Ошибка, о которой нужно сообщить пользователю."""


class UnknownCurrency(ServiceError):
    """Валюты нет в таблице курсов."""


@dataclass(frozen=True)
class Conversion:
    """Результат пересчёта суммы из одной валюты в другую."""

    amount: Decimal
    source: str
    target: str
    result: Decimal
    rate: Decimal
    day: date


class RateService:
    """Получение курсов, кэширование и пересчёт валют."""

    def __init__(self, repository, client, clock=datetime.now,
                 max_lookback=MAX_LOOKBACK):
        """Принять репозиторий, клиент API и источник текущего времени."""
        self.repository = repository
        self.client = client
        self.clock = clock
        self.max_lookback = max_lookback

    def today(self):
        """Текущая дата по часам сервиса."""
        return self.clock().date()

    def get_rates(self, day=None, refresh=False):
        """Таблица курсов на дату day (None — текущие курсы).

        refresh=True — не брать текущие курсы из кэша.
        """
        if day is None:
            return self._current(refresh)
        if day > self.today() + timedelta(days=1):
            raise ServiceError(f"Курсы на {day:%d.%m.%Y} ещё не установлены")
        return self._on_date(day)

    def _current(self, refresh):
        """Текущие курсы: из кэша, если они загружены сегодня."""
        cached = self.repository.latest()
        if cached is not None and not refresh:
            table, fetched_at = cached
            if fetched_at is not None and fetched_at.date() == self.today():
                log.info("Текущие курсы (на %s) взяты из кэша", table.day)
                return table
        try:
            table = self.client.fetch()
        except ApiError as error:
            if cached is None:
                raise ServiceError(str(error)) from error
            log.warning("%s. Показаны сохранённые курсы на %s",
                        error, cached[0].day.strftime("%d.%m.%Y"))
            return cached[0]
        self.repository.save(table, fetched_at=self.clock())
        return table

    def _on_date(self, day):
        """Курсы, действовавшие на дату day (с учётом выходных)."""
        for back in range(self.max_lookback + 1):
            candidate = day - timedelta(days=back)
            table = self.repository.get(candidate)
            if table is not None:
                log.info("Курсы на %s взяты из кэша", candidate)
                break
            try:
                table = self.client.fetch(candidate)
            except NotPublished:
                log.info("На %s курсы не устанавливались, ищу раньше",
                         candidate)
                continue
            except ApiError as error:
                raise ServiceError(str(error)) from error
            self.repository.save(table)
            break
        else:
            raise ServiceError(f"Не найдено курсов за {self.max_lookback} "
                               f"дней до {day:%d.%m.%Y}")
        if day <= self.today():
            # Для прошедших дней (и сегодня) курсы окончательные. Курсы
            # на завтра ЦБ может опубликовать позже — их не запоминаем.
            self.repository.alias(day, table.day)
        return table

    @staticmethod
    def find_rate(table, code):
        """Курс валюты из таблицы или UnknownCurrency с подсказкой."""
        rate = table.get(code)
        if rate is None:
            known = ", ".join([BASE_CURRENCY] + table.codes())
            raise UnknownCurrency(f"Неизвестная валюта {code.upper()}. "
                                  f"Доступны: {known}")
        return rate

    def convert(self, amount, source, target=BASE_CURRENCY, day=None):
        """Пересчитать amount из валюты source в валюту target."""
        if amount <= 0:
            raise ServiceError("Сумма должна быть больше нуля")
        if amount > MAX_AMOUNT:
            raise ServiceError("Слишком большая сумма (не больше 10^15)")
        table = self.get_rates(day)
        source_rate = self.find_rate(table, source)
        target_rate = self.find_rate(table, target)
        rate = source_rate.per_unit / target_rate.per_unit
        result = (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        return Conversion(amount, source_rate.code, target_rate.code,
                          result, rate, table.day)

    def history(self, code, days=7):
        """Курсы валюты за последние days дней: список (дата, Rate).

        Каждая дата установки курса входит один раз: выходные дни
        ссылаются на курсы предыдущего рабочего дня.
        """
        if not 1 <= days <= MAX_HISTORY_DAYS:
            raise ServiceError(f"Число дней — от 1 до {MAX_HISTORY_DAYS}")
        found = {}
        for back in range(days):
            table = self.get_rates(self.today() - timedelta(days=back))
            found[table.day] = self.find_rate(table, code)
        return sorted(found.items())

    def top_changes(self, count=5, day=None):
        """Валюты с наибольшим изменением курса за день (в процентах)."""
        table = self.get_rates(day)
        rates = [rate for rate in table.rates.values()
                 if rate.change_percent is not None]
        rates.sort(key=lambda rate: (-abs(rate.change_percent), rate.code))
        return table, rates[:count]
