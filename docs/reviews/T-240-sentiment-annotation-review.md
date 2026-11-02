# T-240: редакторская sentiment-delta к замороженному корпусу

База — independent checkpoint `400d85f`. Добавлено только `gold.sentiment` всем
162 строкам: **139 negative, 14 neutral, 9 positive**. Annotation revision=2.
Тексты, ID, channel, date, URL, product_line и criticality deep-equal исходным.
[Per-ID labels, причины и text hashes](T-240-sentiment-annotation-review.json).

## Правило и примеры

Каждый текст прочитан по смыслу. Negative — конкретная неисполненная операция,
сбой, ошибочное списание, описанный отрицательный опыт или угроза безопасности.
Positive — явная благодарность за положительный опыт; neutral — вопрос/пожелание
без описанного нарушения. Это редакторская разметка синтетических примеров агентом,
не независимый human-review, не ответ LLM-провайдера и не измеренная accuracy.
Criticality не используется как правило получения sentiment.

- PLV1-0020: **negative + low** — вместо необходимой детализации выписки доступен
  только общий итог, то есть описан недостаток.
- PLV1-0079: **negative + low** — поиск настроек требует проходить несколько меню;
  предложение основано на описанном неудобстве.
- PLV1-0009: **neutral + low** — вопрос о дате процентов без заявленного сбоя.
- PLV1-0015: **positive + low** — благодарность за понятное объяснение.
- PLV1-0001: **negative + high** — не вернулась основная сумма вклада.

Общая family version1 сохраняется; annotation_revision и SHA изменены явно.
Source SHA `642b4159…33e9` → `d70ad54d…e19f`. История исходного пакета остаётся
в commit400d85f и его versioned proof, не переписана задним числом.

## Доверие и применённая узкая projection

Generic CLI/runtime продолжает полностью игнорировать gold, включая sentiment.
Отсутствующее значение — None, не neutral. Verified seed loader требует явную
known sentiment annotation каждой строки и проверяет version/hash/доли.

После root review применена narrow baseline-only projection: known sentiment guard,
UPDATE signals.sentiment/classification.sentiment, metadata source editorial_seed_gold.
Прежние scope run/baseline, external transaction и red-word high priority сохранены.
Нет agent_runs, выдуманного llm_source, usage, ответа модели или accuracy claim.
Gold не становится input модели. Guard неизвестного sentiment оставляет NULL.

47 targeted tests прошли на собственной cx_t240_corpus_revision; отдельный real-PG
assert подтверждает, что обычный import нового gold оставляет signals.sentiment=NULL.
Финальный regression с unknown-guard/provenance: 47 passed, 21.42 с.

History DB adapter ещё не подключён. Утверждённая следующая граница0014:
optional observed Sentiment + sentiment_known_count; новые строки требуют
0≤negative≤known≤signal_count. Legacy known=NULL сохраняет неизвестность;
смешанные legacy/known aggregates показывают unknown quality/NULL, а не
вычисляют фиктивный unknown_count=0 и не переводят неизвестное в neutral.
Actual migration/full seed/API19 ещё не объявляются готовыми.
