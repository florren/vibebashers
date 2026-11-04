# Региональный preview и свежий cache в e2e кабинета

Первый полный nightly на pinned production V4 закончил read-only/settings фазу
143 passed / 7 failed. Два исходных cabinet ru cases зависли после ввода affected=2
в общий калькулятор: UI уже показывал правильные −96,1 ₽, но тест ждал новый HTTP.
До этого региональная карточка получила тот же deposit/affected=2 server preview.
App QueryClient сохраняет свежесть 5000ms; регион и калькулятор намеренно используют
одинаковый scope/input ключ. Новый HTTP при повторе свежих входов не гарантирован.
Timeout также сорвал fixture cleanup: четыре calm cases получили оставшийся v2 layout,
а smoke-theme получил загрязнённые настройки. Эти пять сбоев не скрыты как pass.

Исправляется только тест: manualAffected выбирается отличным от уже проверенного
регионального cohort (3, если региональный2; иначе2). Проверки actual HTTP200 и
денежного значения из server response сохранены. Дополнительно проверяется точное
`server.affected_count === manualAffected`. Production cache/формулы/выплаты/контракты
и таймауты не меняются. Тест не требует лишнего HTTP от правильно работающего cache.

## Доказательства

- Исходный V4:143 passed /7 failed; scenarios/inputs после этого не запускались.
  Полный log/screenshots сохранены в `.runtime/freeze-v4-initial-failed-artifacts`.
- Deterministic real QueryClient hook test (штатный staleTime5000, фиксированный
  Date.now): региональный input2 возвращает server96.1; тот же input калькулятора
  получает96.1 при единственном API call; distinct3 делает второй call. Все4 hook
  tests проходят; TypeScript и ESLint проходят.
- Actual production V4 Chrome на отдельном own native fixture: region16/affected1,
  server48.05 и UI−48,05 ₽. Повтор этих входов в общем калькуляторе дал0 новых HTTP;
  distinct2 дал новый200. Date-only browser clock удерживал cache fresh, timers
  работали обычно. Endpoint/body/суммы не подменялись. External/page errors пусты.
- После коррекции на fresh own native стенде:21/21 actual cabinet/calm/smoke cases
  passed41.4s, включая все ранее упавшие cases. Контейнеры/volumes/network этого
  disposable Compose успешно удалены штатным finally.
- Финальный fresh corrected nightly на том же pinned production image завершён:
  150 read-only/settings +13 native scenarios +5 inputs =168 passed, exit0.
  Performance violations=[]: wall-seed24.31s, p95 всех пяти API≤49.52ms.
  Все7 исходных failures проходят в полном штатном порядке; timeouts не менялись.
  Собственный Compose завершён штатным down -v, primary не затрагивался.

Image V4: `sha256:29da5664fb1f61b26713045b6efdece473796e3e883f0e5c0864ea31cec61da8`.
Machine evidence: `cabinet-preview-cache-e2e-evidence.json`. Private artifacts/logs
сохранены в `.runtime/freeze-cabinet-cache-*`, `.runtime/freeze-v4-corrected-nightly*`.
Все данные synthetic, LLM mock, первичный стенд и внешние сервисы не затрагивались.
Откат — вернуть test input/assertion и удалить новый hook test; production не менялся.
