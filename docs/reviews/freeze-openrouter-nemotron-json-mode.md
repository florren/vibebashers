# OpenRouter Nemotron: JSON mode before inference

## Проверенная причина и граница

Настоящий ограниченный прогон вернул HTTP 200 с upstream error.code=400:
`Grammar error: Unimplemented keys: ["uniqueItems"]`. Usage отсутствовал;
штатный operational ledger сохранил unknown и запретил следующий inference.
Такой ответ нельзя считать нулевым расходом или исправлять автоматическим повтором.

Для exact endpoint host `openrouter.ai` и model
`nvidia/nemotron-3-ultra-550b-a55b:free` producer теперь заранее выбирает существующий
`response_format={"type":"json_object"}`. Compatibility имеет приоритет над
`extra.json_schema=true` и его default. Идентичный model id на другом endpoint,
прочие модели и `extra.json_schema=false` сохраняют прежнее поведение.

Полная семантическая schema остаётся в system prompt (как прежде, только её
metadata title/$id/examples убирается существующим schema_for_model).
Локальная validate_schema работает с полной исходной schema: uniqueItems,
enum, required и остальные ограничения не удаляются. Невалидный ответ получает
прежнюю единственную корректирующую попытку, затем ошибку. Unknown не получает
нового automatic retry. DDL, контракт и caps не меняются.

## Основания

- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs):
  schema format зависит от совместимости модели.
- [OpenRouter Chat API](https://openrouter.ai/docs/client-sdks/python/api-reference/chat):
  JSON object — штатный response_format.
- [NVIDIA guided decoding](https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/features/guided-decoding.html):
  documented XGrammar rejects uniqueItems; JSON object не применяет schema grammar.
  Это подтверждает совместимость подхода, но документация другого NVIDIA runtime
  сама по себе не доказывает реализацию именно данного OpenRouter endpoint.
  Решение для exact model основано на фактическом upstream error выше.

## Проверки

- RED: 3 failed / 3 passed на прежнем producer; HTTP200/error400/absent usage
  воспроизведён через MockTransport.
- GREEN: 32 SDK unit tests, включая actual normalization schema, duplicate intents,
  успешную коррекцию, отказ после двух невалидных ответов, endpoint/model scope.
- 5 native PostgreSQL tests: существующая SDK accounting matrix и новый regression:
  JSON object + HTTP200/error400/no usage → один native unknown;
  повторный вызов → quota, суммарно один HTTP. Только отдельная пустая QA DB.
- Ruff targeted checks passed. Внешних запросов и записей рабочего банка в этих
  проверках нет. Нужен новый отдельно согласованный live прогон исправленного producer.

## Откат

Revert возвращает schema grammar для этого exact model. После upstream отказа
unknown ledger сохраняется и требует штатной operator reconciliation; revert его
не очищает. Рабочие настройки и история не переписываются.
