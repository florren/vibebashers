# Единый final engine diff execution против main

Один instrumented прогон на окончательном source выполнил84 из99 новых
bytecode-executable AST statement starts: **84.85%**. Это единое измерение diff
`origin/main`7fe3f85→final, а не сумма процентов прежних V1/V3/addon proofs.
Порог80% выполнен; дополнительных тестов ради процента не добавлялось.

- Base commit: `7fe3f85f2a2223ccdd016dfaf72f7de44aa55ecc`.
- Final file: `backend/app/sim/engine.py`.
- SHA256: `2216549050deef94a579103a2a9cb6a66926c1653b720cb70cf1a21b48451679`.
- Те же24 native PG/API cases прошли155.43s. Проверены target/resume/lock ownership,
  начальные implicit owners, Stop до первого chunk и между chunks, cancellation
  после committed chunk, сохранение time/RNG и отказ при смене owner.
- Producer и четыре testfiles до запуска побайтово сверены с root candidate.
- Только собственный fresh PG16 и подготовленный pg_dump16, LLM mock, ключи пусты.
  Primary и внешние сервисы не затрагивались; own PG после проверки остановлен.

Метод: stdlib `sys.settrace`, пересечение added diff lines с `ast.stmt.lineno`,
отфильтрованное по bytecode `co_lines` всех вложенных code objects Python3.12.
Исключены non-executable AST headers219/501/575. Это execution statement starts,
не branch coverage, не полное line coverage и не покрытие проекта.

Не выполнены statements511/512,541–547,553/554,614/615/624,654: exception rollback
policy preflight, обычный повторный Start уже работающего demo, rollback snapshot
неудавшегося Start и смена owner перед началом reset_day. Эти ветви не объявляются
проверенными данным24-case trace; дополнительные broad/CI проверки идут отдельно.

Machine evidence: `freeze-final-engine-combined-coverage.json`. Приватный runner,
лог и sanitized source base сохранены в `.runtime/freeze-final-engine-combined-*`.
Production/test source в ходе этой проверки не изменялся.
