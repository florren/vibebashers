# CI210: уменьшение работы privacy projection отчёта

Exact headf55d445 не прошёл два performance gate: общий report p95=355.407ms
(799остальныхpassed/1skipped), cold p95=354.766ms (790остальныхpassed/20skipped).
Cold artifact:30samples,min339.335,p50342.972,max357.875ms,response1799610bytes,
2813signals,SQLexecution26.639ms. Нативные связи/deadlines,fingerprints,NULLstats и
SQLworkbudget до assert прошли. Локально неизменный общий test прошёл1/27.05s;
это не отменяет CI RED и не объясняет конкретный пик.

## Установленный расход и минимальное изменение

Read-only diagnostic на одной synthetic5000 DB: p95до132.180ms,после86.377ms;
median signals stage55.182→29.273ms. Worker cProfile до patch:2845mask calls,
8535regex sub, mask cumulative27ms; эти instrumented значения не acceptance.
Helper всегда запускал email/handle regex даже без@ и numeric regex без цифр.
Они выполняли заведомо бесполезную работу на тысячах обычных строк.

Добавлены только необходимые условия совпадения: numeric regex требует Unicode
`\d`, оба остальных требуют@. Исходные patterns, порядок, replacement и final
slice не меняются. Для numeric guard используется именно `re.search(r"\d")`,
не ASCII-only/isdigit: Unicode semantics сохраняется. Чувствительные строки не
кешируются, общие DTO/память между запросами не появляются. Формулы, SQL, API,
DDL, payload, суммы, HITL и лимиты не меняются; response bytes остаются прежними.
Это подтверждённое локальное уменьшение работы; конкретная причина CI паузы
не доказана, universal latency guarantee не заявляется. Нужен новый полный CI.

## Совместимость и проверка

1572deterministic differential cases сравнивают прежний helper с новым: Unicode
цифры/границы, email/handles/phone/card, длинный текст, None/numbers и6slice limits.
Явный known-contact output и существующие Trace tests:65/65passed. Python stdlib
trace:7/7statement lines helper выполнены, оба исхода каждого нового guard имеют
отдельные cases; это statement coverage, не branch-coverage claim.

Полный backend unit2169passed/19skipped61.25s; Ruff/format563files,mypy327files.
Actual PG report/API/cold-plan69passed207.14s:JSON/XLSX,exact money strings,
role/run scope, native warning evidence, read-only fingerprints. Новый cold test:
p95116.924ms,min108.383,max118.397,30samples/5000clients,SQL16.169ms.
До/после диагностических запросов полный1799610byte JSON имеет один SHA256
63aea01a69b8e29d6734879db3d643daa27ccf18aa36c2d26b61224e6cb7b8e1.
Порог300ms,30requests,firstGET,workbudget,fixture и GC остаются прежними;
warmup, retry или отключения checks нет. Реальных внешних сервисов не вызывали.

[Machine proof](CI-210-report-p95-proof.json), rawCI artifacts сохранены внеGit.
Rollback — revert privacy guard и добавленного compatibility test; данные/историю
не трогать. Предыдущая164browser-приёмка относится к runtime до этой оптимизации;
полный browser CI нового head остаётся обязательным.
