# T-048: диагностический reference при отсутствующем usage OpenRouter

## Проблема и граница

При ответе без `usage` адаптер правильно оставлял попытку `unknown`, однако
терял доступный generation ID и код ошибки провайдера. Это мешало последующей
сверке через `GET /generation?id=...`: ни ledger, ни ошибка графа не содержали
указателя на конкретный запрос. HTTP 200 сам по себе не гарантирует успех модели.

SDK `openai==2.54.0` теперь вызывается через `with_raw_response.create` и синхронный
`parse()`. Успешный ответ, native-schema400 fallback и validation retry используют
прежний путь. Только для OpenRouter при отсутствующем usage в существующий
`ProviderError.detail` добавляются:

- `generation_id`: ASCII `gen-...`, не более128символов, только буквы/цифры/дефис;
- `provider_error_code`: целое HTTP-sized значение100–599 из error envelope.

Если body/header содержат разные допустимые IDs, reference пропускается. Некорректные,
слишком длинные и отражающие credential значения также пропускаются. Raw body,
message, content и посторонние headers в диагностику не копируются. Для local
OpenAI-compatible endpoints прежний текст ошибки сохранён.

`kind=bad_output`, `status`, unknown usage, quota admission, retries, caps, prices и
fallback policy не меняются. Reference не подтверждает расход и не снимает блокировку.
DDL, OpenAPI, события, банковские деньги и HITL-правила не меняются. Уже потерянный ID
этим исправлением задним числом не восстанавливается.

## Проверки

RED: три fakeHTTP200 case (body/header/both ID) не находили reference в ошибке.
GREEN: финальные19новых unit cases; вместе с существующими SDK/security/smoke
136passed/10.42s под coverage.py. Все13новых исполняемых producer lines выполнены
(100%; пересечение added lines с executed/missing lines, не покрытие всего проекта).
Полный unit на том же implementation:2246passed/19skipped; после него добавлены
два из19edge cases без изменения producer и повторён целевой suite.

ActualPG composition с accounting/recovery:51passed/51.24s, собственная PostgreSQL16.
Первый локальный composition имел50passed/1fixtureerror: одновременный fullunit
`gen_schemas` временно удалял generated package при seed subprocess. После завершения
генератора последовательный повтор прошёл целиком; assertions не менялись.

Ruff/format584files, mypy329sources, contracts48schemas/167paths, ownersL1 и
`git diff --check` прошли. Полный exact-head CI остаётся обязательным перед merge.

Новые unit cases покрывают допустимые и конфликтующие IDs, границы длины, ASCII,
credential reflection, некорректные коды, отсутствие error envelope, paid preflight
и неизменный local error. ActualPG cases сохраняют `unknown/bad_output` и счётчик
одной попытки; пересозданный provider не делает второй HTTP. Полный граф сохраняет
reference в `state.errors`, существующем `wait_human.input` и LangGraph checkpoint,
прочитанном новым соединением. Все provider responses фиктивные; рабочих ключей,
баз, inference или reconciliation в проверках нет.

## Источники и восстановление

[Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
описывает автоматический usage; прежний `usage.include` больше не влияет на ответ.
[Generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation)
требует сохранённый ID. [Документация streaming](https://github.com/OpenRouterTeam/docs/blob/main/api_reference/streaming.mdx)
указывает `X-Generation-Id` для корреляции endpoint responses.

Откат: возврат предыдущего adapter возвращает прежнюю диагностику. Existing unknown
и usage records сохраняются; автоматической сверки, повторной отправки или изменения
счётчиков этот пакет не выполняет. Полное хранение provider reference в operational
ledger потребует отдельного additive DDL/review и не входит в этот пакет.
