# T-161 — concrete decision proposal: hazard и legacy churn_risk

**Предложение для review, не одобренная новая policy.** Текущий код не меняет
clients.churn_risk и не записывает туда hazard*100. Одобренные пользователем
значения demo-policy, intent cadence/care и денежные формулы не меняются.

## Подтверждённая граница

ТЗ §4.5 задаёт hazard для очередного sla.tick при текущем waiting/churn_intent и
текущих care/repeat/SLA условиях. Это вероятность параметрического **намерения**
за один шаг; actual churn/закрытие счёта относится к T-164. ТЗ §7 (строка 501)
сохраняет churn_risk как клиентскую контекстную оценку 0..100, отдельно от
negativity. ТЗ §14.4/assessment (строка 794) требует pre-action provenance и не
признаёт неизвестный score калиброванной вероятностью потерь.

Actual consumers: seed clients.py сохраняет исходный synthetic risk; agent
get_client_profile читает его, nodes.py делает существующую контекстную projection
classification churn_risk. Economics evidence читает сохранённый pre-action
score/provenance. API clients detail уже возвращает `state.hazard` и
`state_history[].hazard` отдельно от клиентского churn_risk. Поэтому новый API
field/путь для raw hazard сейчас не требуется.

## Рекомендуемое конкретное решение A

Сохранить действующие producer/consumer semantics churn_risk без изменений до
отдельной T-165 калибровки. Behavior owner пишет только raw hazard в client_states,
с run/client/logical-tick provenance и pinned policy; intent/state определяется
ровно утверждённым draw. Consumer не подменяет клиента risk этим значением.
Для UI/отчёта raw state hazard следует явно называть вероятностью намерения за
15-минутный logical tick, а не вероятностью закрытия/потерь за всё время.

Если это решение принято, точный предлагаемый documentation diff для T-161:

```diff
-2. Запись client_states (is_current), событий client.*, обновление clients.churn_risk.
+2. Запись client_states (is_current), событий client.* и raw per-tick intent hazard.
+   Existing clients.churn_risk и его контекстная projection сохраняются;
+   новое probability mapping/калибровка — отдельная T-165 с provenance review.
```

Это явное уточнение acceptance, поэтому самостоятельно карточка так не изменена.
Пример различия единиц: raw hazard .02 относится к одному шагу; legacy score 60
не становится 2 автоматически. Обе цифры здесь иллюстрируют существующие единицы,
не задают новые defaults или оценку качества/реального банка.

## Альтернатива B, если требуется именно обновлять legacy client risk

До кода требуется отдельный утверждённый calibration contract: что именно
предсказывает score (intent/actual closure), горизонт, conditional state set,
политика накопления/сброса при care/пауза/new episode, historical provenance и
какие money/priority consumers допускают этот источник. После решения нужны
versioned projection и отдельные tests с существующим assessment provenance.
Ни hazard*100, ни накопление 1−product(1−hazard) без этих решений не предлагаются
как runtime mapping: разные горизонты не являются одной вероятностью ухода.

Рекомендовано A для coherent runtime T-161 без скрытого изменения риска/денег;
B остаётся отдельной concrete policy/calibration задачей. Финальный human review
DB/API chain и activation остаётся обязательным независимо от выбранного варианта.
