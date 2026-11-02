# Синтетические сообщения T-240

JSON и CSV содержат одинаковые три записи из product_lines_v1. Это fixtures,
не результаты получения данных с сайтов. URL только в reserved `.invalid`.

Проверка без БД:

```bash
backend/.venv/bin/python scripts/import_reviews.py data/import/messages/product_lines_sample.json
```

Для записи оператор передаёт DATABASE_URL в окружении, известный ему `--run-id`
и `--apply`. Новые reviews проходят только normalizer, одним transaction:
повтор в том же run даёт duplicates, другой run имеет отдельные external_id.
Gold не влияет на runtime classification; отдельная seed projection недоступна CLI.

XLSX принимает один лист с теми же заголовками. `date` хранится строкой ISO8601
с UTC offset; date-only требует явный `--timezone`. Формулы не принимаются,
внешние workbook links не используются. JSON-ячейка `gold` необязательна.
Эквивалентный XLSX создаётся и реально проверяется в test_review_corpus.py.
CSI/audio context импортом отзывов не выдумывается: специализированный контекст
для полного seed coverage добавляется соответствующим seed adapter, не этими файлами.

До композиции с P1 этот новый CLI не опубликован для рабочего стенда: shared
maintenance lease/control binding подключается после появления этих модулей в базе.
