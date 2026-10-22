---
version: v1.1
output_schema: contracts/events/agent/normalization.schema.json
model_hints: быстрая модель (Lightning); один запрос = нормализация + тональность + скрытый негатив
---
Задача: нормализовать текст обращения клиента банка и извлечь признаки.

Верни JSON по схеме normalization:
- language: "ru" или "en".
- summary_ru: суть обращения одним предложением (≤ 200 символов), без ПДн.
- negativity 0–100: 0 — благодарность, ~50 — нейтральная претензия, ≥ 80 — агрессия или угроза ухода.
- sentiment: positive / neutral / negative. Согласуй с negativity: ≤ 33 → positive, 34–66 → neutral, ≥ 67 → negative. Сарказм («спасибо, что списали комиссию, очень удобно») — всегда negative.
- hidden_negativity: sarcasm, passive_aggression («ну да, конечно, разберётесь, как всегда»), churn_threat («подскажите, как закрыть все счета») — для каждого present, confidence и дословная подстрока evidence_ru.
- intents: churn_threat, refund_request, complaint, question, public_shaming, regulator_threat (только явно присутствующие).
- entities: amount_rub (число, если названа сумма), product (deposit/debit_card/credit/credit_card), operation_hint (QR-оплата, перевод, снятие…), date_hint, error_text (цитата ошибки), promo_code, merchant_hint.
- contacts_hint: nickname, masked_phone, masked_card_last4 (4 цифры после ****), city, name — только если явно есть в тексте.
- confidence 0–1.

Пограничные случаи: вопрос без претензии → neutral, intents [question]; благодарность с упоминанием прошлой проблемы → positive, если проблема решена; «закрою счёт, если не вернёте» → negative, churn_threat.present = true.

Подсказки из регулярных выражений (могут быть неполными): {{hints}}

Канал: {{channel}}. Текст обращения:
«{{text}}»
