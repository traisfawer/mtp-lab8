"""Тесты клиента API на requests (задание средней сложности № 2)."""

import os
from datetime import date
from decimal import Decimal

import pytest
import requests

from currency_cli.data import ApiError, CbrClient, NotPublished
from fakes import FakeSession, cbr_json, make_response

USD_JSON = cbr_json(USD=(1, 84.9048, 85.4173), JPY=(100, 53.7032, 54.1061))


def client_with(response=None, error=None):
    """Клиент с поддельной сессией."""
    session = FakeSession(response, error)
    return CbrClient(session=session, base_url="https://api.test/"), session


def test_default_session_is_requests():
    """По умолчанию используется requests.Session."""
    assert isinstance(CbrClient().session, requests.Session)


@pytest.mark.parametrize("day, path", [
    (None, "/daily_json.js"),
    (date(2026, 1, 5), "/archive/2026/01/05/daily_json.js"),
])
def test_url_for(day, path):
    """Адрес текущих курсов и архива (с ведущими нулями)."""
    client, _ = client_with()
    assert client.url_for(day) == "https://api.test" + path


def test_fetch_parses_table():
    """Ответ API превращается в таблицу курсов."""
    client, session = client_with(make_response(payload=USD_JSON))
    table = client.fetch()
    assert table.day == date(2026, 10, 10)
    assert table.codes() == ["JPY", "USD"]
    jpy = table.get("JPY")
    assert (jpy.name, jpy.nominal) == ("Иен", 100)
    assert session.calls == [("https://api.test/daily_json.js", 10)]


def test_values_are_exact_decimals():
    """Курсы читаются как Decimal без погрешностей float."""
    client, _ = client_with(make_response(payload=USD_JSON))
    usd = client.fetch().get("USD")
    assert usd.value == Decimal("84.9048")
    assert usd.previous == Decimal("85.4173")


def test_archive_404_is_not_published():
    """404 для архивной даты — курсы не устанавливались."""
    client, _ = client_with(make_response(status=404, text="Not found"))
    with pytest.raises(NotPublished):
        client.fetch(date(2026, 10, 11))


def test_current_404_is_api_error():
    """404 для текущих курсов — это сбой API, а не выходной."""
    client, _ = client_with(make_response(status=404, text="Not found"))
    with pytest.raises(ApiError) as info:
        client.fetch()
    assert not isinstance(info.value, NotPublished)


def test_server_error():
    """Ошибка сервера превращается в ApiError с кодом ответа."""
    client, _ = client_with(make_response(status=503, text="down"))
    with pytest.raises(ApiError, match="HTTP 503"):
        client.fetch()


@pytest.mark.parametrize("error", [
    requests.ConnectionError("нет сети"),
    requests.Timeout("долго"),
])
def test_network_errors(error):
    """Нет связи или истёк таймаут — ApiError."""
    client, _ = client_with(error=error)
    with pytest.raises(ApiError, match="Нет связи"):
        client.fetch()


@pytest.mark.parametrize("response", [
    make_response(text="<html>не JSON</html>"),
    make_response(payload={"Date": "2026-10-10"}),
    make_response(payload=cbr_json(USD=(1, "много", 1))),
])
def test_bad_payload(response):
    """Некорректный или неполный ответ — ApiError."""
    client, _ = client_with(response)
    with pytest.raises(ApiError):
        client.fetch()


@pytest.mark.skipif(not os.environ.get("CURRENCY_LIVE"),
                    reason="обращение к сети: CURRENCY_LIVE=1 pytest")
def test_live_api():
    """Интеграционный тест с настоящим API ЦБ."""
    table = CbrClient().fetch()
    assert "USD" in table.rates and table.get("USD").value > 0
