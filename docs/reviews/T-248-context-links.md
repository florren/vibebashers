# T-248: реальные CSI/ВСП ссылки на Trace и поиск

Два native regression сначала воспроизвели ошибки: строковый код ВСП0042
интерпретировался как PK42 чужого ВСП; accepted CSI-030208 превращался вCSI-30208
и давал404. Изменение branch trace_path использует actual numeric PK с run_id;
точный CSI lookup сохраняет ширину принятого external_id. История и IDs не
переписываются, прежняя canonical parse grammar сохраняется.

Public CSI lookup применяется только к CSI-prefixed query. Numeric search
сохраняет преобразование Unicode decimal черезint: промежуточный повтор выявил
неверное применение CSI helper к numeric lookup (79pass/1fail); оно исправлено.
Финальный повтор80unit/actualPG passed110.05с, Ruff и mypy312 green. Проверены
actual GET Trace, exact global Search hit, пагинация/readonly fingerprints,
Unicode numeric variants и существующие journey/search сценарии.
