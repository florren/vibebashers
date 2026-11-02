# Источники независимого review T-021

`T-021-independent-review.json` скопирован из независимого отчёта основного
агента без подмены per-case решений. Исходное case-level agreement — 197/200
(98.5%), все восемь полей каждого кейса просмотрены. Поздние исправления
подтверждены в follow_up и provenance_follow_up; raw agreement сохранён.
Временные /tmp пути внутри исходного машинного отчёта — provenance рабочего
процесса reviewer, не актуальные пути для загрузки датасета.

Актуальные [JSONL и manifest](../../data/golden/README.md) находятся в data/golden;
reviewed v2 snapshot хранится в Git commit f1090e7, v3/v4 восстанавливаются по
проверенным deltas. Canonical loader проверяет текущие SHA и всю цепочку approvals.
Это corpus review, не автоматическое разрешение merge кода или операций на БД.
