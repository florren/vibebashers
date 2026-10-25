---
version: v1.1
output_schema: contracts/events/compliance/transcript_report.schema.json
model_hints: основная модель; на mock-провайдере отчёт собирается из находок правил
---
Задача: составить отчёт по качеству обслуживания по транскрипту встречи сотрудника банка с клиентом.

Верни один JSON-объект строго с полями схемы transcript_report. Не копируй title, $id и examples схемы. Других полей нет.

Поля:
1. `findings` — массив подтверждённых нарушений. Каждый элемент: `turn_seq` (номер реплики с 1), `pattern_code` (tie_in, substitution, concealment, pressure, guarantee, rudeness, script_violation, misinformation), `family` (misselling или conduct), `confidence` (0..1), `quote` (дословная подстрока реплики, до 300 символов), `explanation_ru` (до 300), `recommendation_ru` (до 400). Для misinformation добавь `fact_check`: `claim`, `truth`, `source_table` (products, tariffs, dcltv_rates, service_scripts, economics_settings), `source_key`, `verified`. `alert_policy`: immediate, report или counter. Нейтральные реплики не включай.
2. `script_compliance` — объект `{script_code, steps}`. `script_code` = {{script_code}}. В `steps` этапы greeting, identification, needs, offer, summary, closing: `code`, `status` (done, partial, missed, not_applicable), `evidence_turn_seq` или null.
3. `overall_ru` — 2–4 предложения, до 600 символов: о чём встреча и главные нарушения.
4. `action_plan_ru` — 2–4 конкретных действия руководителю, до 800 символов.
5. `confidence` — уверенность отчёта от 0 до 1.

Факты банка: {{facts}}
Предварительные находки правил: {{preliminary}}
Этапы скрипта по правилам: {{script_steps}}

Транскрипт:
{{transcript}}
