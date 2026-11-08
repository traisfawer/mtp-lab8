"""Задание средней сложности № 8: модуль с интерфейсом командной строки.

Командная строка разбирается модулем argparse: подкоманды, позиционные
аргументы, необязательные ключи, собственные типы с проверкой значений,
справка -h и версия --version. Это слой представления: он только
разбирает аргументы, вызывает слой сервисов и печатает результат.

Примеры:
    currency rates                    — все курсы на сегодня
    currency rates USD EUR CNY        — выбранные валюты
    currency rates --date 2026-10-04  — курсы на дату
    currency rates --top 5            — сильнее всего изменившиеся
    currency convert 100 USD EUR      — пересчёт суммы
    currency history USD --days 14    — история курса
"""

import argparse
import logging
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from currency_cli import __version__
from currency_cli.data import CbrClient, SqliteRateRepository
from currency_cli.services import ServiceError, RateService

DEFAULT_DB = Path.home() / ".currency-cli" / "rates.db"


def positive_amount(text):
    """Тип argparse: положительная сумма («1 000,50» тоже подходит)."""
    try:
        value = Decimal(text.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise argparse.ArgumentTypeError(
            f"«{text}» — не число") from None
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("сумма должна быть больше нуля")
    return value


def currency_code(text):
    """Тип argparse: трёхбуквенный код валюты (usd → USD)."""
    code = text.strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise argparse.ArgumentTypeError(
            f"«{text}» — не код валюты (пример: USD)")
    return code


def iso_date(text):
    """Тип argparse: дата в формате ГГГГ-ММ-ДД."""
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"«{text}» — не дата в формате ГГГГ-ММ-ДД") from None


def positive_int(text):
    """Тип argparse: целое число больше нуля."""
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value <= 0:
        raise argparse.ArgumentTypeError(
            f"«{text}» — нужно целое число больше нуля")
    return value


def build_parser():
    """Создать парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        prog="currency",
        description="Курсы валют ЦБ РФ: просмотр, пересчёт и история.",
        epilog="Подробнее о команде: currency КОМАНДА -h")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="файл кэша курсов (по умолчанию %(default)s)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="подробный вывод: -v — что делается, "
                             "-vv — отладка")
    commands = parser.add_subparsers(dest="command", required=True,
                                     metavar="КОМАНДА")

    rates = commands.add_parser("rates", help="курсы валют")
    rates.add_argument("codes", nargs="*", type=currency_code,
                       metavar="КОД", help="коды валют (по умолчанию все)")
    rates.add_argument("--date", type=iso_date, metavar="ГГГГ-ММ-ДД",
                       help="дата (по умолчанию — текущие курсы)")
    rates.add_argument("--refresh", action="store_true",
                       help="загрузить заново, не используя кэш")
    rates.add_argument("--top", type=positive_int, metavar="N",
                       help="N валют с наибольшим изменением за день")
    rates.set_defaults(handler=show_rates)

    convert = commands.add_parser("convert", help="пересчитать сумму")
    convert.add_argument("amount", type=positive_amount, metavar="СУММА")
    convert.add_argument("source", type=currency_code, metavar="ИЗ")
    convert.add_argument("target", type=currency_code, nargs="?",
                         default="RUB", metavar="В",
                         help="валюта результата (по умолчанию RUB)")
    convert.add_argument("--date", type=iso_date, metavar="ГГГГ-ММ-ДД",
                         help="по курсу на дату")
    convert.set_defaults(handler=show_conversion)

    history = commands.add_parser("history", help="история курса валюты")
    history.add_argument("code", type=currency_code, metavar="КОД")
    history.add_argument("--days", type=positive_int, default=7,
                         help="за сколько дней (по умолчанию %(default)s)")
    history.set_defaults(handler=show_history)
    return parser


def format_number(value, places=4):
    """Число с разделителем тысяч: 12345.6 → «12 345.6000»."""
    return f"{value:,.{places}f}".replace(",", " ")


def format_change(rate):
    """Изменение курса за день: «+0.5125 (+0.60 %)»."""
    if rate.change is None:
        return "—"
    return f"{rate.change:+.4f} ({rate.change_percent:+.2f} %)"


def format_table(rows, headers):
    """Текстовая таблица с выравниванием по ширине столбцов."""
    table = [list(map(str, headers))] + [list(map(str, row)) for row in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    lines = [" | ".join(cell.ljust(width) for cell, width
                        in zip(row, widths)).rstrip() for row in table]
    lines.insert(1, "-+-".join("-" * width for width in widths))
    return "\n".join(lines)


def rate_rows(rates):
    """Строки таблицы курсов."""
    return [(r.code, r.name, r.nominal, format_number(r.value),
             format_change(r)) for r in rates]


def show_rates(service, args):
    """Команда rates: вывести курсы."""
    headers = ["Код", "Валюта", "Номинал", "Курс, руб.", "За день"]
    if args.top:
        table, rates = service.top_changes(args.top, args.date)
        print(f"Сильнее всего изменились за день "
              f"(курсы ЦБ РФ на {table.day:%d.%m.%Y}):")
    else:
        table = service.get_rates(args.date, refresh=args.refresh)
        codes = args.codes or table.codes()
        rates = [service.find_rate(table, code) for code in codes]
        print(f"Курсы ЦБ РФ на {table.day:%d.%m.%Y}:")
    print(format_table(rate_rows(rates), headers))


def show_conversion(service, args):
    """Команда convert: пересчитать сумму."""
    result = service.convert(args.amount, args.source, args.target,
                             args.date)
    print(f"{format_number(result.amount, 2)} {result.source} = "
          f"{format_number(result.result, 2)} {result.target}")
    print(f"Курс ЦБ РФ на {result.day:%d.%m.%Y}: 1 {result.source} = "
          f"{format_number(result.rate)} {result.target}")


def show_history(service, args):
    """Команда history: история курса валюты."""
    history = service.history(args.code, args.days)
    name = history[-1][1].name
    print(f"{args.code} ({name}) за {args.days} дн.:")
    print(format_table(
        [(f"{day:%d.%m.%Y}", rate.nominal, format_number(rate.value),
          format_change(rate)) for day, rate in history],
        ["Дата", "Номинал", "Курс, руб.", "За день"]))


def configure_logging(verbosity):
    """Настроить вывод журнала в stderr по числу ключей -v."""
    levels = {0: logging.WARNING, 1: logging.INFO}
    level = levels.get(verbosity, logging.DEBUG)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s",
                        force=True)


def main(argv=None, client=None, clock=datetime.now):
    """Точка входа утилиты currency. Возвращает код завершения.

    client — источник курсов (по умолчанию API ЦБ), clock — часы.
    Тесты передают сюда подделки, чтобы не ходить в сеть и не зависеть
    от текущей даты.
    """
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    if str(args.db) != ":memory:":
        args.db.parent.mkdir(parents=True, exist_ok=True)
    repository = SqliteRateRepository(args.db)
    service = RateService(repository, client or CbrClient(), clock=clock)
    try:
        args.handler(service, args)
    except ServiceError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    finally:
        repository.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
