# Freeze v2: target advancement и конкурентные Pause → Start

Дополнение к `freeze-sim-control-serialization.md`; основа — engine candidate
f297480 (SHA256 ece6965466f56058ea6bd3f0f094a5e77fe145baaac9ef70714c495165cd06ec).

## Подтверждённые дефекты

1. Behavior reset_day рассчитывал relative minutes до захвата lock следующего
   chunk. Concurrent ручной step между native chunks не вычитался из оставшегося
   интервала. Два настоящих POST /api/sim/control возвращали200, но reset_day
   завершался09:01 вместо09:00. Jump_to имел ту же ошибку для target дальше одного
   chunk. Регрессия фиксирует timeline реальных _step_chunk_locked: чужой step
   расположен между первым и последним target chunk, а не после достижения цели.
   Поэтому допустимый step после завершения target не ошибочно считается overshoot.
2. Start без label проверял paused/interrupted до ожидания Python lock. Pause,
   завершившаяся до preflight либо между preflight и mutation lock, могла дать
   running clock при paused run. В special demo ветке статус становился running,
   но штатные resume hooks и resumed_count пропускались.
3. Cached demo_execution после Stop мог повторно активировать тот же завершённый
   run и очистить его finished_sim/finished_at. Теперь mutation перечитывает профиль:
   disabled/stopped выходит из special demo path и обычный Start создаёт новый run.
4. Late resume handoff не должен удерживать SQL guard row после release Python lock.
   Иначе queued worker держит Python lock и ждёт SQL row, а resume ждёт Python lock.
   Native PG расписание воспроизвело этот deadlock для simulation/demo.

ASGI maintenance gate не сериализует обычные control requests: это admission/drain,
а PostgreSQL boundary использует shared advisory lock. Оба расписания достигнуты
через настоящий create_app/HTTP/PG16, без AST-подмены production методов.

## Изменение

- Private _step_to под тем же Python lock на каждом chunk заново рассчитывает
  remaining = target − current и выполняет прежний _step_chunk_locked (≤60 минут).
  Чужой step внутри продвижения учитывается; прямого прыжка часов behavior нет.
- Request pin текущего run предотвращает продолжение старого target на новом run.
  Только первый chunk, начатый под lock без run или при completed/stopped/archived,
  может принять штатный implicit free run из _ensure_world. Затем pin неизменен.
  Смена owner либо Stop до завершения target вызывает409 до новых эффектов;
  committed chunks остаются, чужой текущий run не продвигается.
- Start повторно выбирает resume после protected preflight и непосредственно
  внутри обычного/demo mutation lock. Вызов resume_run всегда снаружи lock;
  применяются прежние hooks, policy checks, journal/resumed_count и row guards.
  Read-only guard TX откатывается под owned Python lock до handoff/fallthrough;
  shared native tick в этот момент завершён и не может быть откатан этим rollback.
- Early уже-paused/interrupted path сохранён. Размеры обычных шагов, native timers,
  rollback/cancellation `_step_chunk_locked`, формулы, суммы, лимиты и HITL не меняются.

API/DDL/event schemas не меняются. История автоматически не редактируется.
Фикс не сериализует все долгие controls одним общим mutex: Pause не блокируется
на весь многочасовой target, а конкурентный step между chunks остаётся разрешён.

## Проверки

- Native HTTP RED target:2failed15.22s (reset_day и jump_to125min), обе парыPOST200.
- Native HTTP RED resume:4failed25.71s (simulation/demo × во время Pause TX /
  после Start preflight). Проверяются не только clock/status, но hooks/resumed_count.
- Первичный GREEN source579fa41:8passed47.56s; broad85passed528.54s,
  coverage54/62=87.10%. Этот provisional source имел введённую ошибку pin при
  штатном implicit owner, поэтому эти результаты не объявляются финальным gate.
- RED введённой pin-регрессии:4failed31.06s (None/stopped/completed/archived).
  Исправление принимает только допустимый implicit owner первого owned chunk.
- Финальный адресный GREEN:19passed126.09s:13 новых cases, пять прежних lock
  regressions и один factory/RNG rollback control. Включён Stop между chunks.
- В финальном тесте cancellation дополнительно включены реальные native operations,
  чтобы RNG действительно менялся до отмены; run replacement не продвигает новый run.
- Source EA1 после implicit-owner fix:19 plain passed126.09s,72 composition
  passed462.66s; coverage62/70=88.57%. Эти результаты не покрывают следующий v3.
- Native RED DemoStop:1failed8.69s. Guard-row worker RED:3failed30.48s
  (два5s deadlock timeout и ошибочное повторное открытие остановленного demo run).
- Финальный v3 адресный GREEN:23passed144.41s. Это17 новых native/API cases,
  пять прежних lock regressions и один factory/RNG rollback case.
- Финальная v3 composition:72passed484.55s (stale time/RNG/status guards,
  controls, behavior timers, Team/RNG recovery, maintenance/OS crash/lock ordering).
  Всего95 plain PG cases на финальном source вместе с23 адресными.
- Отдельный instrumented v3 прогон:23passed198.84s; stdlib sys.settrace
  выполнил69/79 bytecode-executable AST statement starts добавленного diff against
  f297 engine (87.34%). Non-executable headers219/573 исключены по Python3.12
  co_lines. Это не branch coverage и не заявление о полном покрытии проекта.
- Ruff check/format, strict mypy engine и git diff --check прошли.
- Exact final engine SHA256:
  8515750ec3b7f13598152c643e94ef5635c699b27af480bcdde7580d8bfe6b9b.

Все стенды собственные PG16; LLM mock, внешних вызовов и primary writes нет.

## Финальная review-граница и откат

Вместе с v1 это защита владения общей native tick транзакцией, включая сохранённые
экономические факты. Новый target учитывает уже выполненный чужой step, а resume
не пропускает штатные hooks; новые денежные решения или human accept не добавляются.
Финальное human review требуется по AGENTS.md §5.1 («всё, что касается денег и HITL»).

Откат к f297480 после остановки тестового runtime возвращает обе гонки.
Уже сохранённые записи не переписываются; автоматического ремонта старых запусков нет.

## Дополнительный final review: Stop до первого target chunk

В source851575 Stop после preflight, но до первого owned chunk ещё мог создать
новый free run: native HTTP RED2 (jump_to65min/reset_day). Допуск implicit owner
теперь сохраняется под preflight lock и передаётся `_step_to`; более поздний Stop
не меняет этот допуск. Штатный исходный None/stopped/completed/archived сохранён.

Финальный addon:24 native PG/API cases passed155.72s,6/6 новых исполняемых
statement starts выполнены; JSON `freeze-first-chunk-stop-coverage.json`.
Независимый observer после409 проверяет exact current_run_id/time/RNG/stopped.
Это новое адресное доказательство; прежние95cases выше source-qualified к851575.
Ruff check/format и mypy нового engine прошли. Полный combined gate выполняется.
Новый финальный engine SHA256:
2216549050deef94a579103a2a9cb6a66926c1653b720cb70cf1a21b48451679.
