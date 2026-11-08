"""Тесты интерфейса командной строки (задания № 8 и повышенной № 4)."""

import argparse
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from currency_cli import __version__
from currency_cli.cli import (currency_code, iso_date, main, positive_amount,
                              positive_int)
from currency_cli.data import ApiError
from fakes import FakeClient, friday_table, saturday_table

NOW = datetime(2026, 10, 11, 15, 0)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def run(tmp_path, capsys):
    """Запустить main с подделками; вернуть (код, stdout, stderr).

    «Сегодня» для утилиты — воскресенье 11.10.2026.
    """
    def runner(*argv, client=None):
        client = client or FakeClient([friday_table(), saturday_table()],
                                      current=saturday_table())
        code = main(["--db", str(tmp_path / "rates.db"), *argv],
                    client=client, clock=lambda: NOW)
        out, err = capsys.readouterr()
        return code, out, err

    return runner


@pytest.mark.parametrize("text, value", [
    ("10", "10"), ("1 000,50", "1000.50"), ("0.01", "0.01"),
])
def test_positive_amount(text, value):
    """Сумма: запятая и пробелы допустимы."""
    assert positive_amount(text) == Decimal(value)


@pytest.mark.parametrize("text", ["0", "-1", "abc", "nan", "inf", ""])
def test_positive_amount_invalid(text):
    """Неположительные и нечисловые суммы отклоняются."""
    with pytest.raises(argparse.ArgumentTypeError):
        positive_amount(text)


@pytest.mark.parametrize("text, code", [("usd", "USD"), (" Eur ", "EUR")])
def test_currency_code(text, code):
    """Код валюты приводится к верхнему регистру."""
    assert currency_code(text) == code


@pytest.mark.parametrize("text", ["US", "USDT", "дол", "U5D"])
def test_currency_code_invalid(text):
    """Только три латинские буквы."""
    with pytest.raises(argparse.ArgumentTypeError):
        currency_code(text)


def test_date_and_int_types():
    """Дата ГГГГ-ММ-ДД и положительное целое."""
    assert iso_date("2026-10-09") == date(2026, 10, 9)
    assert positive_int("7") == 7
    for function, text in [(iso_date, "09.10.2026"), (positive_int, "0"),
                           (positive_int, "семь")]:
        with pytest.raises(argparse.ArgumentTypeError):
            function(text)


def test_rates(run):
    """Команда rates выводит таблицу курсов."""
    code, out, _ = run("rates")
    assert code == 0
    assert "Курсы ЦБ РФ на 10.10.2026" in out
    assert "USD | Доллар США | 1       | 84.9048    | -0.5125 (-0.60 %)" \
        in out


def test_rates_selected_codes(run):
    """Можно выбрать валюты; порядок — как в командной строке."""
    _, out, _ = run("rates", "jpy", "USD")
    lines = out.splitlines()
    assert lines[3].startswith("JPY") and lines[4].startswith("USD")
    assert len(lines) == 5


def test_rates_on_weekend_date(run):
    """Курсы на воскресенье — субботние."""
    _, out, _ = run("rates", "USD", "--date", "2026-10-11")
    assert "Курсы ЦБ РФ на 10.10.2026" in out


def test_rates_top(run):
    """Ключ --top показывает самые изменившиеся валюты."""
    _, out, _ = run("rates", "--top", "1")
    assert "Сильнее всего изменились" in out
    assert out.splitlines()[-1].startswith("KZT")


def test_convert(run):
    """Команда convert пересчитывает сумму."""
    code, out, _ = run("convert", "100", "usd")
    assert code == 0
    assert out.splitlines() == [
        "100.00 USD = 8 490.48 RUB",
        "Курс ЦБ РФ на 10.10.2026: 1 USD = 84.9048 RUB",
    ]


def test_history(run):
    """Команда history выводит курсы по датам."""
    code, out, _ = run("history", "USD", "--days", "3")
    assert code == 0
    assert "USD (Доллар США) за 3 дн." in out
    assert "09.10.2026 | 1       | 85.4173" in out


@pytest.mark.parametrize("argv, message", [
    (["convert", "10", "XYZ"], "Неизвестная валюта XYZ"),
    (["rates", "--date", "2030-01-01"], "ещё не установлены"),
    (["history", "USD", "--days", "99"], "от 1 до 31"),
])
def test_service_errors(run, argv, message):
    """Ошибки слоя сервисов: код 1 и сообщение в stderr."""
    code, out, err = run(*argv)
    assert code == 1
    assert out == ""
    assert message in err


def test_offline_without_cache(run):
    """Без сети и кэша — код 1 и понятное сообщение."""
    code, _, err = run("rates", client=FakeClient(error=ApiError(
        "Нет связи с https://www.cbr-xml-daily.ru: ConnectionError")))
    assert code == 1
    assert "Ошибка: Нет связи" in err


@pytest.mark.parametrize("argv", [
    [], ["rates", "--top", "0"], ["convert", "-5", "USD"],
    ["convert", "10", "доллар"], ["unknown"],
])
def test_bad_arguments(run, argv):
    """Неверные аргументы: argparse завершает работу с кодом 2."""
    with pytest.raises(SystemExit) as info:
        run(*argv)
    assert info.value.code == 2


def test_version(run, capsys):
    """Ключ --version печатает версию пакета."""
    with pytest.raises(SystemExit) as info:
        run("--version")
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == f"currency {__version__}"


def test_verbose_logging(run):
    """С ключом -v в stderr пишется, откуда взяты курсы."""
    run("rates")
    _, _, err = run("-v", "rates")
    assert "INFO: Текущие курсы (на 2026-10-10) взяты из кэша" in err


def test_output_fits_windows_encoding(run):
    """Вывод не содержит символов вне cp1251 (перенаправление в файл)."""
    for argv in (["rates"], ["convert", "5", "JPY", "EUR"],
                 ["history", "EUR"]):
        _, out, _ = run(*argv)
        out.encode("cp1251")


def test_python_m_entry_point():
    """Пакет запускается командой python -m currency_cli."""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
               PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-m", "currency_cli",
                             "--version"], capture_output=True, text=True,
                            encoding="utf-8", env=env, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == f"currency {__version__}"
