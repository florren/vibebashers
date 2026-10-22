---
version: v1.1
output_schema: contracts/events/agent/classification.schema.json
model_hints: основная модель (Ultra/Max); few-shot из human_decisions.use_as_fewshot
---
Задача: классифицировать обращение клиента банка и объяснить решение.

Таксономия signal_type (ТЗ §7):
- tech_fault — технический сбой: ошибка при открытии вклада, зависший платёж, двойное списание. Если в контексте есть активный сбой системы на пути операции клиента — это tech_fault с этим error_code.
- client_error — ошибка/непонимание клиента: ожидал промо-ставку после окончания акции, неверные реквизиты, не прочитал условия.
- tariff_terms — претензия к тарифам/условиям: «необоснованная» комиссия, не та ставка. Комиссия за оплату по QR/СБП для физлиц — нарушение правила банка (ошибочное списание), error_code PROC-QR-FEE-CHARGED, продукт debit_card, система processing.
- service_quality — качество обслуживания: грубость, очередь, долгий ответ.
- fraud_suspicion — подозрение на мошенничество: звонок «из службы безопасности», неизвестное списание.
- legal_regulatory — иск, арест счёта, жалоба в ЦБ/прокуратуру (всегда критично, нужен человек).
- info_request — вопрос без претензии; gratitude — благодарность; suggestion — предложение.

Флаги: churn_intent (намерение уйти), repeat (повторное обращение по той же причине — см. контекст), sarcasm, aggression, mass_impact (в контексте ≥ 3 связанных клиентов/инцидент по тому же коду), passive_aggression, hidden_negativity, regulator_threat, public_shaming.

Поля:
- product и system должны быть согласованы (deposit → sub_deposits/promo_engine; debit_card → processing/sub_debit; credit/credit_card → sub_lending).
- cause_hypothesis — гипотеза причины из того же перечня типов или unknown.
- criticality — базовая по типу (§7), tone — одно из neutral/positive/irritated/angry/sarcastic/formal.
- churn_risk 0–100 — про клиента с учётом контекста (сегмент, повторы, угрозы), negativity — про текст.
- sentiment — positive/neutral/negative, согласованно с нормализацией.
- confidence 0–1 — честная уверенность; при противоречивом тексте ≤ 0,6.
- summary_ru — суть одним предложением; rationale_ru — 2–4 предложения: почему такой тип, какие факты из контекста подтверждают, что неясно. Не повторяй текст сигнала дословно.
- problem_summary: problem (≤ 2 предложений, ≤ 300 символов, без ПДн), severity (low/medium/high; critical — только если high и при этом угроза регулятору, мошенничество > 50 000 ₽, массовость или угроза ухода vip/ultra_vip), suggested_team — код команды из списка: {{teams}}.

Примеры решений людей (few-shot): {{fewshot}}

Контекст (клиент, продукты, операции за 72 сим-часа, активные сбои, прошлые сигналы и открытые инциденты):
{{context}}

Нормализация (быстрая модель): {{normalization}}

Канал: {{channel}}. Текст обращения:
«{{text}}»
