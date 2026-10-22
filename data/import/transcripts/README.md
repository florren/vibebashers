# Транскрипты для импорта (B07)

Форматы: JSON по `contracts/events/ingest/transcript.schema.json` и TXT вида `[чч:мм:сс] Сотрудник: …` / `Клиент: …`
(строки `# key: value` в начале TXT — метаданные: kind, branch, employee, desk, deal_product, client_id, external_id).

- `scenario09_branch_misselling.json` — сценарий 9: подмена продукта, сокрытие условий, навязывание → порог 3 → алерт руководителю.
- `scenario10_retail_red_phrases.txt` — сценарий 10: грубость и неверная ставка (14 % вместо 9,5 %) → немедленный алерт; пропущены этапы «Потребности» и «Резюме».
- `clean_contact_center_call.txt` — чистый разговор контакт-центра без нарушений (контроль ложных срабатываний).

Импорт: `POST /api/ingest/transcripts/import` (каталог по умолчанию — этот) или `make scenario ID=9`.
