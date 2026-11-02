# Golden-наборы T-021

Источники истины — `golden_v1.jsonl` (200 кейсов) и `lite_v1.jsonl` (40).
Файлы с теми же именами в `data/bench/` — точные compatibility mirrors;
`gen_corpora.py` копирует их из этого каталога и не генерирует неполный gold.
Публичные dataset codes и существующие file/DB bench interfaces сохранены.

В golden по 20 кейсов каждого из 10 контрактных типов; все 12 каналов имеют
16–17 кейсов. Lite содержит по 4 кейса на тип, каналы имеют по 3–4 кейса;
это точное строгое подмножество golden, включая text, gold, tags и annotations.
64/200 текстов (32%) имеют содержательные `sarcasm`, `multi_topic` или
`implicit_product`. Это сложность понимания текста, отдельная от SLA `complexity`.
Неназванные product/system имеют null, скрытая банковская подсистема не угадывается.
Факты, влияющие на gold, находятся в model input: client-visible error codes,
операции/суммы и явный объём исправления из ответа банка. Gold/annotations
никогда не добавляются в классификационный prompt.

Все восемь gold fields проверяются по контрактным enum, bool/flags и основаниям.
Маршрут — первая команда действующих routing rules, а не придуманное правило
разметчика. Источник этой версии — main `3c1c12c` (T-014); file hashes в manifest.
`needs_hitl` относится к явно описанному baseline mass/confidence1/repeat_count1/
no gift. Функции политик и их лимиты не изменялись. Classify runner по прежнему
контракту оценивает type/product/system/criticality/route; остальные reference
поля не превращаются в выдуманные новые accuracy metrics.

Независимый полный pass всех 200 inputs и восьми полей выполнил основной агент,
отдельно от автора корпуса. Исходное строгое case-level согласие v2 — 197/200,
98.5%. Три ошибки исправлены отдельным v3 delta review; затем в v4 исправлено
только имя функции в provenance (`human_reason` → `needs_human`). Новых gold/text
изменений v4 нет. Raw agreement не пересчитан задним числом в 100%.
[Полный машинный отчёт](../../docs/reviews/T-021-independent-review.json) сохраняет
все 200 решений и оба follow-up approvals. Runtime читает ту же запись из
`data/golden/review_v1.json`, которая входит в image/data volume; docs не нужны
в production image. В checkout обе копии проверяются на точное совпадение. `ready_to_merge=false` в исходной
части отчёта означает, что corpus approval не заменяет проверку кода/CI.
V2 воспроизводится из WIP commit `f1090e7`; v3 — его явно проверенная delta;
финальные SHA v4 и исходные hashes находятся в `manifest_v1.json`.

`ambiguous` исключается из каждого accuracy denominator и critical recall,
но остаётся в latency/JSON-validity/cost/stability. Tags сохраняются в file и DB
runner и JSON/CSV exports; source id дополнительно хранится в DB tags как
`dataset-case:GOLD-XXXX`. В lite ambiguous запрещены. В текущем корпусе известные
спорные метки разрешены review, непроверенных ambiguous gold нет.

## Проверка и загрузка

```bash
backend/.venv/bin/python scripts/seed/bench.py --check
```

Проверяются строгий JSON (без duplicate keys/NaN), полный gold, enum/типы,
уникальность id/text, баланс, hard coverage, exact subset/mirrors и соответствие
независимого review текущим hashes. Этот автоматический gate проверяет целостность
свидетельства, а не выдаёт себя за новый семантический review. Изменённому корпусу
нужно новое независимое согласование. Обычный seed создаёт свежий canonical dataset
и идемпотентно повторяет точное содержимое; старый несовпадающий набор не заменяет.

## Явный upgrade существующей БД

Не запускайте команды на основном стенде без отдельного разрешения владельца.
Укажите свой DSN через `DATABASE_URL`: CLI не читает `.env` и не использует
неявный localhost default. DSN не выводится в plan/logs. Автоматического upgrade
в startup/обычном seed нет.

```bash
# DATABASE_URL уже задан для явно выбранной БД; сначала только чтение.
backend/.venv/bin/python scripts/seed/bench.py --plan > bench-upgrade-plan.json
# После проверки плана используйте его plan_sha256, не DSN в аргументах.
backend/.venv/bin/python scripts/seed/bench.py --apply --plan-sha <plan_sha256>
```

`--plan` работает в repeatable-read READ ONLY transaction. План содержит только
id, counts, hashes и предлагаемые коды, не исходные тексты/секреты. Если старое
содержимое или metadata отличается, предлагается архив
`family@legacy-{old_id}-{content_hash_prefix}`. Hash архива вычисляется из реальных
DB cases; source SHA нового canonical — из reviewed JSONL. Это разные provenance
поля. Коллизия archive code и queued/running bench старого ID блокируют upgrade.

`--apply` повторно вычисляет план под advisory + dataset row locks, проверяет
plan SHA и применяет обе семьи одной transaction. Меняются только code и
provenance description старого `bench_datasets`; ни старые cases/results, ни
их IDs не обновляются/удаляются. История bench_runs продолжает ссылаться на тот
же archived dataset id. Новый dataset со stable logical code получает новые ID.
File bench продолжает работать с canonical reviewed JSONL; DB bench может
читать и rerun исторические archived cases по их dataset id. После успешного
upgrade точный повтор — no-op. Смена корпуса/состояния после preview требует
нового плана; блокировки/коллизии/ошибки не скрываются.

Ошибка в любой семье откатывает весь upgrade, включая уже выполненную первую
семью. PostgreSQL sequence может оставить пропуски ID после rollback — это
нормально и не меняет существующие ID. При сбое/обрыве соединения после возможного
commit повторите `--plan`: exact-current canonical означает завершённый upgrade;
повтор `--apply` ничего не дублирует.

Для возврата после успешного upgrade не удаляйте новые cases/results. После
остановки активных benchmark jobs возьмите transaction и те же dataset locks,
проверьте old/new id и hashes из сохранённого плана. Переименуйте новый canonical
в отдельный свободный archival code, затем верните нужному legacy id stable
family code, сохранив обе истории. Это отдельная явно согласуемая операция,
не автоматический rollback script; обычный revert исходников данные БД не откатит.
Нельзя менять gold существующих cases для «исправления» старых результатов.

Верификация upgrade использует только собственную scratch БД: read-only plan,
actual operator CLI apply/retry, сохранение старых cases/results/IDs, active/
collision/stale rejection и injected failure второй семьи с полным rollback.
Новых зависимостей/DDL/API schema fields нет; license inventory не расширяется.
