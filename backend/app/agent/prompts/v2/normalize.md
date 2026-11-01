---
version: normalize-v2
output_schema: contracts/events/agent/normalization.schema.json
model_hints: быстрая модель (Lightning); один запрос = нормализация + тональность + скрытый негатив
---
Задача: нормализовать текст обращения клиента банка и извлечь признаки.

Верни JSON по схеме normalization:
- language: "ru" или "en".
- summary_ru: суть обращения одним предложением (≤ 200 символов), без ПДн.
- negativity 0–100: 0 — благодарность, ~50 — нейтральная претензия, ≥ 80 — агрессия или угроза ухода.
- sentiment: positive / neutral / negative. Согласуй с negativity: ≤ 33 → positive, 34–66 → neutral, ≥ 67 → negative. Сарказм («спасибо, что списали комиссию, очень удобно») — всегда negative.
- hidden_negativity всегда содержит ВСЕ три объекта: sarcasm, passive_aggression («ну да, конечно, разберётесь, как всегда»), churn_threat («подскажите, как закрыть все счета») — для каждого present (boolean), confidence (число 0–1, никогда null) и evidence_ru (дословная цитата либо null). При отсутствии признака: {"present": false, "confidence": 1.0, "evidence_ru": null}.
- intents: churn_threat, refund_request, complaint, question, public_shaming, regulator_threat (только явно присутствующие).
- entities: amount_rub (число, если названа сумма), product (ровно одно deposit/debit_card/credit/credit_card либо null, не массив), operation_hint (ТОЛЬКО qr_payment/card_payment/transfer/withdrawal/deposit/loan_payment/notification/login либо null; не русское название операции и не autopayment), date_hint, error_text (цитата ошибки), promo_code, merchant_hint.
- contacts_hint — объект (при отсутствии контактов {}, никогда null): nickname, masked_phone, masked_card_last4 (4 цифры после ****), city, name — только если явно есть в тексте.
- confidence 0–1.

Пограничные случаи: вопрос без претензии → neutral, intents [question]; благодарность с упоминанием прошлой проблемы → positive, если проблема решена; «закрою счёт, если не вернёте» → negative, churn_threat.present = true.

Скрытый негатив — в том же JSON, отдельный вызов модели не делай. evidence_ru — дословная подстрока текста, иначе null.
Примеры (класс → present):
1. «Спасибо, что списали комиссию, очень удобно» — sarcasm, evidence «очень удобно», sentiment negative, negativity ≥ 60.
2. «Ну да, конечно, разберётесь, как всегда» — passive_aggression, evidence «как всегда».
3. «Подскажите, как закрыть все счета, пора менять банк» — churn_threat, evidence «закрыть все счета».
4. «Прекрасно, просто прекрасно. Закрываю вклад» — sarcasm и churn_threat.
5. «Очень приятно видеть комиссию второй раз» — sarcasm, evidence «Очень приятно».
6. «Ну конечно, перевод “мгновенный”, третий день жду» — sarcasm и passive_aggression.
7. «Спасибо большое, кэшбэк пришёл, всё честно» — искренняя благодарность, все present=false, sentiment positive.
8. «Как закрыть вклад при переезде, без претензий» — нейтральный вопрос, churn_threat.present=false.
9. «Добрый день, какая ставка по вкладу на 6 месяцев?» — вопрос, hidden present=false.
10. «Верните 450 рублей за QR, пожалуйста» — refund без сарказма, sarcasm.present=false.
11. «Идиоты, заблокировали карту» — агрессия без скрытого негатива: sarcasm.present=false, negativity ≥ 80.
12. «Ничего, подожду, не в первый раз» — passive_aggression, evidence «не в первый раз».

Подсказки из регулярных выражений (могут быть неполными): {{hints}}

Канал: {{channel}}. Текст обращения:
«{{text}}»
