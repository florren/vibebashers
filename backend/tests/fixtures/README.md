# Записанный synthetic bank replay v1

`replay_bank_v1.json` фиксирует контекст реальной v1.1 кассеты
`174508311da29178f016ba3094e36291612a740c37427ff51ec4dedeede099a0`
из `data/cassettes/gigachat.jsonl`. Общий lazy fixture в `tests/conftest.py`
используется offline replay08 и trace12/13. Клиент, продукт, sim_time и sequence
соответствуют записанному prompt; это отдельный банк, не новый random seed.
Исходные assertions completed/replay/ledger/client_lane сохранены.

T-017 изменил context нового банка: client/products/operations и operation_ids
[4801] вместо [2179]. На старом contract schema и user text кассеты совпадают;
после нормализации пробелов вне context/rules JSON prompt идентичен. T-018 logs
не подгоняются под старую запись. Отдельный сценарный тест подтверждает honest
miss нового seed и явно отмеченный fallback_mock, не выдавая его за replay.
Request hashes, responses, usage и timestamps кассет не изменяются.

Fixture проверяет исходный request_hash по реальным messages и текущей schema.
Расширение common.schema меняет hash вложенной instant_decision schema: старый
record станет stale и тест честно упадёт. Совместимость с ещё не одобренным новым
contract не заявляется. Нужна отдельно разрешённая новая реальная запись на frozen
synthetic bank; rekey старых live-ответов и расширение matching запрещены.
