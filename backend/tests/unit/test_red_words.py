from __future__ import annotations

import pytest

from app.agent import policies
from app.ingest.red_words import detect

POSITIVE = [
    "Подам в суд",
    "Обращусь в суд!",
    "Решение суда",
    "Суду переданы документы",
    "Спор с судом",
    "Дело в суде",
    "Судебная претензия",
    "Судебное решение",
    "Судебный приказ",
    "Судебные расходы",
    "Судебному приставу",
    "Судебного приказа копия",
    "Подаю иск",
    "Требования иска",
    "Ответ по иску",
    "Пришёл с иском",
    "Речь об иске",
    "Иски направлены",
    "Исковое заявление",
    "Исковые требования",
    "Исковая давность",
    "Копия искового заявления",
    "Налоговая списала",
    "Иду в налоговую",
    "Запрос налоговой",
    "Справка налогового органа",
    "Жалоба в ФНС",
    "ФНС требует ответ",
    "Исполнительный лист",
    "Копия исполнительного листа",
    "По исполнительному листу",
    "Жалоба в ЦБ",
    "ЦБ проверит",
    "Письмо Центральному банку",
    "Центральный банк ответил",
    "Мисселлинг пенсионеру",
    "Жалоба на мисселинг",
    "Факт мисселлинга",
    "СУД",
    "ФнС: ответьте",
]
NEGATIVE = [
    "Высокий риск",
    "Оценка риска",
    "Риски инвестиций",
    "Управление риском",
    "Рискованный вклад",
    "Буду искать карту",
    "Искать в приложении",
    "Я ищу перевод",
    "Таксист оплатил",
    "Оплата таксиста",
    "Нужно исключить дубль",
    "Исключение из правил",
    "Купил сосуд",
    "Пустая посуда",
    "Здравый рассудок",
    "Обсуждение тарифа",
    "Искусство экономить",
    "Искусственный интеллект",
    "Дисконт на карту",
    "Поиск перевода",
    "Просто спасибо",
    "Миссия банка",
    "Цветок на окне",
    "Доставка посуды",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_red_words_detected(text: str) -> None:
    result = detect(text)
    assert result["words"], text
    assert all(text.casefold().replace("ё", "е")[m["start"] : m["end"]] == m["text"] for m in result["matches"])


@pytest.mark.parametrize("text", NEGATIVE)
def test_no_false_positive(text: str) -> None:
    assert detect(text)["words"] == []


@pytest.mark.parametrize(
    "word,expected", [("иск", True), ("ЦБ", True), ("суд", True), ("мисселлинг", False), ("риск", False)]
)
def test_legal_hitl_independent_of_llm(word: str, expected: bool) -> None:
    c = {"signal_type": "service_quality", "confidence": 1.0, "red_words": [word]}
    assert policies.red_words_require_hitl(c) is expected
    assert policies.needs_human(c, policies.PolicyContext()) == ("legal_regulatory" if expected else None)
