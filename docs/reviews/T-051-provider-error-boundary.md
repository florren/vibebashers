# T-051: provider errors, SDK logging и usage metadata

## Подтверждённая граница

Synthetic MockTransport показал два обхода прежней защиты. SDK500 с credential в error.message давал безопасный ProviderError.detail, но formatted traceback включал raw SDK cause. Giga200 с credential в usage.prompt_tokens вызывал ValueError до проверки model output; его текст содержал credential. Никакие реальные LLM/credentials не использовались.

Mapped upstream exceptions теперь используют `from None`: сохраняются kind/status/retry/usage, raw cause не попадает в стандартный formatted traceback. В текущих provider handlers до mapped raise нет logging raw exception; ожидаемые ошибки фонового Giga refresh пишут только error_type. Это защита вывода, не обещание удаления private exception objects из памяти.

## Явное изменение SDK logging policy

Installed openai2.54 использует loggers `openai`, `openai._base_client`, `openai._response`, `openai._legacy_response`. DEBUG включает headers/transport traceback/непрочитанный response, INFO — retry URL. В проверенной установленной версии эти SDK-модули не испускают WARNING/ERROR с upstream body/headers.

На owned client boundary, после SDK import/env logging setup, для этих exact loggers действует minimum WARNING; более высокий существующий уровень сохраняется. Повторная проверка перед SDK chat/stream закрывает повторную настройку debug до wire. `OPENAI_LOG=debug` больше не включает raw SDK diagnostics для этих клиентов. Root logger, `logging.disable`, app structlog и httpx level не меняются. App status/kind/retry/usage diagnostics остаются. При обновлении SDK inventory/logger policy надо перепроверить.

Regression subprocess запускается с настоящим `OPENAI_LOG=debug`, Fake HTTP500 header/body echo, transport exception и invalid JSON. Проверяются traceback, настоящий console и JSONL, отсутствие credential и единственный Fake request. Старые cached structlog handles не переносятся между subprocess.

## Совместимость usage

- Exact credential в prompt/completion/total metadata отклоняется ДО числового parsing.
- Prompt/completion counts обязательны для успешного non-stream response: missing/invalid metadata не возвращается как успешный нулевой usage. Ошибка bad_output имеет usage=None. Это также касается прежнего free/local response без usage.
- Bool, negative, fractional/nonfinite и malformed values отвергаются constant diagnostic без raw values/cause. Giga сохраняет прежнее осмысленное integer coercion: whitespace numeric strings и integer-valued floats принимаются. SDK counts остаются строгими int.
- Valid explicit0 принимается; missing total выводится из подтверждённых prompt+completion, а explicit total0 сохраняет прежний Giga fallback на сумму. Числовые rates/prices/limits не меняются.
- Нет validated wire usage — overall ProviderError.usage=None. Если первый response подтверждён, а новый wire failed, overall расход неизвестен; предыдущие per-key known observations остаются. Late content/schema refusal после valid usage сохраняет known usage. Прежний successful JSON retry sum60 не изменён.
- Stream сохраняет подтверждённые cumulative counts при ошибке; missing metadata не становится0. Usage-only SSE с choices=[] поддержан без IndexError; отказ после уже выданного prefix не разрешает fallback.

Это конкретный error/metadata compatibility change для human review. Durable UTC/RPD/wire-attempt ledger остаётся отдельно T-050 P2/0016; здесь не создаются новые лимиты или billing store. Банковские refund/HITL правила не меняются. Защита ограничена exact credentials и поддержанными JSON decoding formats; универсальный DLP/произвольные кодировки не заявляются.

## Проверки checkpoint

193 provider/SDK/budget/benchmark tests прошли8.56s; отдельный85-test boundary/benchmark прогон прошёл6.45s после согласованной None-vs0 wire guard. Composed financial/runtime/durable/bench/replay target58passed249.38s до последней narrow wire guard; новый итоговый head будет проверен отдельно. Числа frozen727 в соседнем отчёте не объявляются full green этого изменённого source.

Bounded audit завершён: known credential также проверяется в публично потребляемых model IDs и GET/key projection до передачи вызывающему коду; private unused labels не проверяются/не возвращаются, default limits и valid metadata сохранены. Internal `ProviderError.request_count` сохраняет прежний adapter generation-attempt counter независимо от UsageNone. Chain добавляет его только при неизвестном usage; known usage count не удваивается. Это не all-HTTP/durable counter и не P2 ledger. Согласованный target197passed7.73s; отдельные no-doublecount и прежний backup-count cases3passed0.76s.
