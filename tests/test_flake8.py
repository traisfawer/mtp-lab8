"""Проверка стиля как часть тестов (задание средней сложности № 6).

flake8 запускается с настройками из файла .flake8 в корне проекта.
Если в коде появится нарушение, упадёт этот тест — и, значит, вся
проверка проекта.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(importlib.util.find_spec("flake8") is None,
                    reason="flake8 не установлен")
def test_flake8_clean():
    """В проекте нет замечаний flake8."""
    result = subprocess.run([sys.executable, "-m", "flake8"], cwd=ROOT,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    assert result.returncode == 0, result.stdout


def test_flake8_config():
    """Файл настроек flake8 на месте и задаёт основные параметры."""
    config = (ROOT / ".flake8").read_text(encoding="utf-8")
    for option in ("max-line-length", "max-complexity",
                   "docstring-convention", "extend-exclude"):
        assert option in config
