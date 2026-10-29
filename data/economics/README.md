# Данные калибровки и политики прототипа

demo-controls.jsonl содержит 2 000 синтетических записей (разные клиенты для train/validation). Скоры и исходы сгенерированы; это механизм демонстрации, не реальная NLP-оценка и не банковская статистика. demo-calibration.json допускается только в demo, для mock:mock-rules-v1, v1.1, agent-score-v1, graph v1. registry.json оставляет observed-калибровку и observed-политику null.

```bash
backend/.venv/bin/python scripts/gen_churn_demo.py
backend/.venv/bin/python scripts/calibrate_churn.py --input data/economics/demo-controls.jsonl --metadata data/economics/demo-metadata.json --output /tmp/demo-calibration.json
```

Оба результата должны совпасть с версией в Git. Хеш набора — SHA256 канонического JSON списка разобранных записей (ключи сортируются, пробелы исключаются, Unicode сохраняется), а не сырого JSONL. Артефакт также содержит собственный SHA256 без поля artifact_sha256.

Входная строка: client_ref (обезличенный уникальный id), split=train|validation, scope=demo|observed, model, prompt_version, score_pipeline, score (0–100), horizon_days=7, predicted_sim, observed_until_sim, churned_sim (ISO с поясом либо null), treated=false. Нельзя включать клиента дважды, смешивать источники или скармливать исход после cutoff. Для нулевого исхода требуется наблюдение полного горизонта, отсутствие записи об уходе само по себе отрицательным классом не считается. Не используйте ПДн или секреты в id/ссылках.

Метаданные задают id, scope, data_kind=synthetic_controls|observed_controls, model, prompt_version, horizon_days=7, cutoff_sim, business_approval_ref и описание population. Рабочий набор должен быть реально наблюдаемым, обезличенным, контрольным и согласованным; mock и синтетическая маркировка отклоняются. Сначала постройте артефакт CLI и оцените отчёт, затем внесите его относительный путь в calibrations.observed через review. Копирование демо-артефакта с переименованием не является рабочей калибровкой.

Рабочая fine_policies.observed задаётся отдельно: id/версия, scope=observed, RUB, amount_rub (копейки), unit=deal, basis_ref, business_approval_ref, legal_approval_ref, effective_from_sim/effective_until_sim, additive_to_dcltv. Наличие строк не доказывает подлинность документов: её проверяют ответственные до внесения доверенной конфигурации. Демо-политика 50 000 ₽ — явно условный пример без юридического согласования; она не допускается в observed.

Доказательства в API ссылаются на политику и источники, но не загружают их автоматически. Политика/калибровка не дают разрешения двигать деньги; формула ADR-0007, refund_fee и HITL сохраняются. Полный алгоритм и ограничения — docs/adr/ADR-0014-finance-calibration-evidence.md.
