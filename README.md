# Лабораторная работа № 8. Экосистемы Python, их использование

**Ефимов Денис Борисович, группа 220042-11, вариант 6, лабораторная №8**

Дисциплина «Методы и технологии программирования» (часть 1).

`currency-cli` — консольная утилита курсов валют ЦБ РФ: просмотр курсов,
пересчёт сумм, история курса. Данные — API https://www.cbr-xml-daily.ru
(официальные курсы ЦБ в формате JSON).

## Задания варианта 6

Средней сложности:
- № 6 — настроить flake8 — `.flake8`, `tests/test_flake8.py`;
- № 8 — модуль с CLI на argparse — `src/currency_cli/cli.py`;
- № 2 — добавить зависимость requests — `poetry add requests`
  (`pyproject.toml`, `poetry.lock`), используется в
  `src/currency_cli/data/api_client.py`.

Повышенной сложности:
- № 4 — CLI-утилита с Poetry — команда `currency`
  (`[project.scripts]` в `pyproject.toml`), сборка `poetry build`;
- № 10 — слой сервисов + слой данных — `src/currency_cli/services.py`
  и пакет `src/currency_cli/data/`.

## Архитектура

```
cli.py            слой представления: argparse, вывод таблиц
   │
services.py       слой сервисов: кэш, выходные дни, работа без сети,
   │              пересчёт валют через рубль
   ├── data/api_client.py   слой данных: API ЦБ (requests)
   └── data/repository.py   слой данных: хранилище (шаблон Repository)
                            SqliteRateRepository / InMemoryRateRepository
models.py         модель: Rate, RateTable (Decimal вместо float)
```

- Слой сервисов не знает про HTTP, SQL и командную строку: клиент API
  и репозиторий передаются ему в конструктор (внедрение зависимостей),
  поэтому в тестах их легко заменить подделками.
- Курсы в выходные: ЦБ их не устанавливает (архив отвечает 404),
  поэтому для воскресенья берутся субботние курсы; связь
  «воскресенье → суббота» сохраняется, повторный запрос идёт без сети.
- Текущие курсы кэшируются на день; без интернета показываются
  сохранённые курсы с предупреждением.

## Установка (Poetry)

```
pip install poetry
poetry install
```

`poetry install` создаёт окружение `.venv` в папке проекта
(настройка `poetry.toml`), ставит `requests` и dev-зависимости
(pytest, flake8, flake8-docstrings, pep8-naming) и сам пакет.

## Использование

```
poetry run currency rates                    # все курсы на сегодня
poetry run currency rates USD EUR CNY        # выбранные валюты
poetry run currency rates --date 2026-10-04  # на дату (в выходной — последние установленные)
poetry run currency rates --top 5            # сильнее всего изменившиеся
poetry run currency convert 100 USD EUR      # пересчёт суммы
poetry run currency convert "1 000,50" JPY   # в рубли
poetry run currency history USD --days 14    # история курса
poetry run currency -v rates                 # с журналом (откуда взяты данные)
poetry run currency -h                       # справка
```

Кэш курсов — `~/.currency-cli/rates.db` (ключ `--db` задаёт другой файл).

На Windows, если путь к проекту содержит русские буквы, сгенерированный
Poetry файл `currency.cmd` не запускается (cmd.exe читает его в кодировке
консоли). В этом случае используйте `poetry run python -m currency_cli ...`
или установите собранный пакет — у pip команда `currency.exe` работает
из любого пути:

```
poetry build
pip install dist/currency_cli-1.0.0-py3-none-any.whl
currency rates USD
```

## Проверка стиля (flake8)

```
poetry run flake8
```

Настройки — в `.flake8` (flake8 не читает `pyproject.toml`): длина строки
79, сложность функций (mccabe) не больше 8, документация по PEP 257
(flake8-docstrings), имена по PEP 8 (pep8-naming). Тест
`tests/test_flake8.py` запускает flake8, поэтому любое замечание
стиля проваливает тесты.

## Тесты

```
poetry run pytest -v
```

117 тестов. Сеть в тестах не используется: клиенту передаётся поддельная
сессия requests, сервису — поддельный клиент. Тесты репозитория
выполняются для всех трёх вариантов хранилища (память, SQLite в памяти,
SQLite в файле). Проверка с настоящим API:
`CURRENCY_LIVE=1 poetry run pytest` (на Windows:
`set CURRENCY_LIVE=1` и затем `poetry run pytest`).
