---
version: v1.0
output_schema: contracts/events/compliance/transcript_report.schema.json
model_hints: основная модель; на mock-провайдере отчёт собирается из находок правил
---
Задача: составить отчёт по качеству обслуживания по транскрипту встречи сотрудника банка с клиентом. Ответ строго по JSON-схеме transcript_report.

Что нужно:
1. `summary_ru` — 2–4 предложения: о чём встреча, что продано/обсуждено, главные проблемы.
2. `findings` — подтверждённые нарушения (из таксономии tie_in, substitution, concealment, pressure, guarantee, rudeness, script_violation, misinformation) с цитатами, уверенностью, рекомендациями. Нейтральные реплики не включай.
3. `script_steps` — этапы скрипта {{script_code}}: greeting, identification, needs, offer, summary, closing — статус done/missed/skipped и доказательства.
4. `manager_actions_ru` — 2–4 конкретных действия руководителю (разбор с сотрудником, перезвонить клиенту, модуль обучения).
5. `client_signal` — если клиент жаловался или просил о чём-то, кратко: тема, тональность, требуется ли обращение.

Факты банка: {{facts}}
Предварительные находки правил: {{preliminary}}
Этапы скрипта по правилам: {{script_steps}}

Транскрипт:
{{transcript}}
