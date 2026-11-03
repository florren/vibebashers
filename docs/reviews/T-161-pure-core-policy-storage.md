# T-161: pure core, policy и durable storage — предложение к review

Источник аудита: `f2ac951ab00626cc718e79f732393ed391f04bba`. Реализация ограничена
`app/sim/behavior/model.py`; runtime её не импортирует. DDL, wiring, настройки,
финансовые формулы и существующие значения психотипов не менялись.

## Проверенные границы

`World.pending` теряется после restart. `TextGen` использует отдельный RNG; root
готовит отдельную T-031 коррекцию его инъекции. Доказательства T-041 относятся к
agent checkpoint и не доказывают восстановление очереди World. `EventBus.emit`
сохраняет событие и transactional NOTIFY, но не dispatch/consumer cursor.
`TwinService.react` непосредственно заменяет care_score значением satisfaction.
Сейчас отсутствует владелец параметрических state/care/hazard переходов.

## Реализованное чистое ядро

Состояния берутся из сгенерированного `ClientState`, параметры — из
`PsychotypeParams`, вероятности и задержки — только из переданного `SimRng`.
`Snapshot`, evidence и результаты переходов неизменяемы. Выход не пишет БД,
не создаёт signal, не закрывает счёт, не выставляет таймер и не делает commit.
Повторный вызов не является идемпотентным: отсеивание duplicate evidence до
потребления RNG — обязанность будущей transaction/repository границы.

Обязательная `BehaviorPolicy`: segment_multiplier, retained_threshold и
care_strategy. Defaults отсутствуют. Стратегия получает предыдущий care_score,
тип/ID/сим-время evidence и read-only веса из текущего каталога; её результат
проверяется на конечность и диапазон. Проверяются веса и порядок delay bounds.
Числа тестовой стратегии и threshold присутствуют только в тестах и не являются
принятыми правилами продукта.

Формула hazard буквально соответствует ТЗ §4.5. Raw hazard не обрезается.
Сравнение RNG draw с hazard даёт достоверное событие при hazard ≥ 1. Событие
`client.*` при этом ещё не сериализуется: контрактное ограничение требует решения.
Ни hazard, ни вероятность не превращаются автоматически в clients.churn_risk.

## Неопределённая policy: решения до runtime

1. **segment_multiplier**: в текущем behavior-каталоге не задан. Варианты для
   review — явная конфигурация всех сегментов либо отдельная калибруемая карта.
   Значений по умолчанию в core нет.
2. **care components**: веса определены, но преобразование скорости/объяснения/
   тона/подарка в наблюдения, их накопление и decay не определены. Варианты —
   нормированные component observations с weighted aggregation либо явно
   утверждённые event deltas. Это ADR-0006 follow-up, не скрытый кодовый выбор.
   Satisfaction двойника — отдельное наблюдение, не готовая замена care_score.
3. **retained_threshold**: требуется числовая конфигурация и область действия.
   Core возвращает retained при достижении порога; ниже порога возвращает None,
   потому что конкретный следующий исход не определён. Фактическое закрытие
   счёта/incident/loss принадлежит T-164.
4. **complaint episode**: core запрещает повторное affected для активного episode.
   Нужна семантика одного fault/op, нескольких продуктов и регрессии. Иначе
   fault.started + op.failed создадут двойную жалобу и двойной RNG draw.
5. **silent_decline**: pure candidate трактует вероятность как условную после
   решения «не жаловаться». Требуется явное подтверждение условной/безусловной
   трактовки; runtime не включён.
6. **hazard cadence / probability**: SLA сейчас может emit дополнительный tick на
   хвосте batch. Нельзя молча менять вероятность из-за разбиения времени.
   Варианты — фиксированные логические 15-минутные моменты либо согласованный
   time-normalized hazard с изменением ТЗ. Raw hazard > 1 и контракт [0,1] также
   требуют review: ограничение разрешённого входа или явная вероятность отдельно
   от raw величины. Pure core формулу не меняет.
7. **churn_intent → closure**: HazardDecision возвращает только triggered,
   raw_hazard и переход в churn_intent. Повторный hazard не запрашивает закрытие.
   Терпение patience_days и business-calendar deadline должны войти в будущую
   согласованную policy/T164. Ни один счёт не закрывается.
8. **clients.churn_risk**: диапазон БД 0..100 не доказывает линейную шкалу hazard.
   Нужна утверждённая проекция, не умножение на 100 по догадке.

## Предлагаемая storage/ownership граница (не DDL)

После P1/schema chain review: provisional migration 0017 (0014 — T240, 0015 — T121, 0016 — P2), если
будет принята необходимость следующих таблиц. Номер не закреплён файлом.

- Runtime row UNIQUE(run_id, client_id): текущий state ID, episode/related source
  links, component observations, repeat/SLA факты; typed storage contract с
  version вместо произвольного скрытого JSON. FK run cascade.
- Durable work/receipt: UNIQUE(run_id, source_kind, source_id, action), due_sim,
  bounded typed payload, consumed marker. Отдельные задачи для complaint/repeat/
  patience; входные notifications/twin reactions сохраняются как evidence.
- client_states остаётся историей transitions. Перед unique current(run,client)
  нужны диагностика и явное разрешение существующих дублей, без тихого удаления.

Tick под существующим Sim._lock читает committed evidence в стабильном порядке,
обрабатывает due work, записывает receipt/state/events, создаёт сигналы только
через normalizer и сохраняет RNG одной транзакцией. Ошибка откатывает всё.
External workers не используют RNG модели и не меняют care/state напрямую.
Процесс после crash повторяет только unconsumed work. Закрытие запуска исключает
новые переходы, foreign run не затрагивается; baseline/archive охватывают FK data.

T-039 получает тот же causal fault evidence и полный список affected клиентов из
БД (sample50 не является полным списком). T-020 использует pure правила с
явными historical bindings. T-163 отдаёт реакцию/evidence общей state boundary.
Протоколы handle_event/advance/observe_notification будут repository adapters;
сейчас core содержит решения без фиктивного DB API.

## Проверки и оставшаяся работа

Unit-проверки: 1000 клиентов **на каждый** из восьми психотипов, фиксированный
seed, ±3 п.п. и silent_churner ≤15%; реальные delay bounds; точная формула;
care рост/падение на явно тестовой стратегии; repeat/escalation; порог; неверные
входы; RNG round-trip. Это не production calibration и не OS restart proof.

Перед завершением T-161 нужны policy/ADR/storage review, runtime integration,
real PG rollback/receipt/concurrency tests, OS-process restart до/после due,
равенство events/signals/RNG, run isolation, baseline/archive, затем полный suite.
Карточка не done. Новых dependencies, вызовов LLM и операций с БД не было.

### Локальная проверка pure checkpoint

- `pytest backend/tests/unit/test_behavior_model.py backend/tests/unit/test_textgen.py -q`:
  **31 passed** (27 новых behavior + 4 существующих textgen).
- Ruff check/format для новых файлов и mypy `app/sim/behavior`: green.
- `git diff --check`: green.
- Дополнительно пытались собрать `test_sim_baseline.py`: collection остановился
  на `ModuleNotFoundError: No module named 'openai'` в существующем LLM import.
  Использован существующий canonical venv; новых dependencies и изменений
  окружения не было. Это не падение behavior-теста; широкий regression не доказан.
- Никаких DB, prod, LLM или иных runtime/external вызовов не выполнялось.

Дополнение review: `repeat` в формуле ТЗ может означать bool или число повторов.
Поэтому `hazard`/`sla_tick` требуют отдельный keyword input `repeat`; фактический
`Snapshot.repeat_count` автоматически в формулу не подставляется. Выбор bool/count
принадлежит policy review. Нет неявного default.

Финальная проверка checkpoint после обязательного repeat input: **46 passed**
(28 behavior + 4 textgen + 14 baseline), 2.71 с. Использован read-only frozen
`t048-openai-sdk/backend/.venv` через symlink своего checkout и абсолютный
PYTHONPATH своей backend/root. Initial missing-openai gap устранён выбором
разрешённого готового окружения, без установки/изменения общих dependencies.
Остаётся существующий Starlette TestClient deprecation warning. Полный suite
не запускался: runtime не подключён; карточка остаётся in_progress.

### Узкий quality follow-up

Строгие guards: source_id — положительный int, не bool; Snapshot.state —
сгенерированный ClientState; repeat_count — неотрицательный int, не bool;
sla_breached — bool. Policy/care отвергают bool и нечисловые значения.
Явный repeat в формуле пока допускает bool: трактовка bool/count не выбрана.
Удалено предположение о закрытии после второго hazard. Комментарии/docstrings
нового ядра и тестов приведены к русскому языку.

Повторная проверка: **70 passed** (52 behavior + 4 textgen + 14 baseline),
Ruff check/format и mypy ядра green. Runtime/БД по-прежнему не подключены.


Подготовлено отдельное неактивное предложение по новому запросу пользователя:
[ADR-0024](../adr/ADR-0024-demo-client-behavior-policy.md),
[demo YAML](../../data/behavior/demo_policy.review.yaml),
[offline sensitivity](T-161-demo-policy-sensitivity.json).
Первоначально это было proposal без одобрения. 02.11.2026 пользователь явно
подтвердил значения/семантику `ba5145d` для реализации; approval metadata теперь
записана в YAML/ADR, enabled=false. Pure core/runtime и действующие defaults пока
не менялись. Новые API/DB contracts требуют финального конкретного review.

## Typed care checkpoint после одобрения demo-policy

Пользователь одобрил значения/семантику `ba5145d`; approval metadata зафиксированы
в `b6cdb5c`, enabled=false. Новое чистое ядро `behavior/care.py` реализует явные
CareComponents/CareState/CareContext/CareResult и Communication/SLA/Gift evidence.
В snapshot входят first_reply_at, sticky tone violation и SLA breach; стратегия
не хранит частную память в closure. Score округляется ROUND_HALF_UP один раз после
полной weighted sum, веса не нормализуются повторно.

Статусы совпадают с существующим notifications.status: queued/sent/delivered/
failed/suppressed. Только sent/delivered дают credit; queued не трактуется как
физически отправленное сообщение или gift offer. Атрибуция клиенту и валидность
T015 обязательны и не выводятся из наличия произвольного текста. Invalid message
не даёт положительный credit и может обнулить tone sticky; последующее правильное
сообщение нарушение не стирает. Gift требует done+issued+sent offer; personal_call
не создаёт gift fit, несколько подарков берут максимум, а не сумму.

First reply выбирается по самому раннему допустимому факту после реальной жалобы;
позднейшее по sim_time сообщение не переписывает delay. Более ранний исходный
факт, доставленный writer позже, восстанавливает истинное first_reply_at.
Это конкретная обработка evidence ordering, не новая probability/policy цифра;
перед wiring writer обязан получать исходные timestamps и подтверждённые связи.

### Граница durable writer (пока не реализована)

Будущая 0017 имеет actual parent0016 после T2400014/T1210015/P2, но файл миграции
здесь отсутствует. Commit owner — одна tick transaction: lock(run,client), receipt
по реальному source_kind/id/action ДО RNG, typed component snapshot, timers,
state/events/signals и SimRng.dump_state атомарно. Episode хранит immutable policy
hash/version и реальный набор fault/operation cause membership. Нет private queue,
модель не делает commit и не подтверждает причинность сама.

Коммуникационный producer должен читать настоящий transport status, run/client,
включая явно привязанный public reply; queued outbox и глобальная рассылка без
атрибуции не дают care. Синтетический bool от клиента не является evidence.
TwinService direct care_score UPDATE подлежит переносу в единственного владельца;
client_reactions.satisfaction остаётся наблюдением, а не заменой care. До этой
композиции runtime loader/actor wiring отсутствует, enabled=false сохраняется.
Долговечность World.pending текущим checkpoint не утверждается.

Проверено:89 pure tests (60 прежних+29 новых) passed0.37s; changed Ruff/mypy green.
Care module executable coverage177/190=93.16% exact absolute-file trace; raw proof
`T-161-care-components-proof.json`. Внешних вызовов, БД, DDL и финансовых/HITL
изменений нет. Это scoped checkpoint, не done всей T161.
