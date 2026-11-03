# Карточка ведущего: freeze demo

**Черновик, не репетиция.** Минуты — план. Основа `4107a01396ec8bffccb6746945cf996f9ade894f` (T0926f066 + preparation1fb + recovery report). До общего фриза нужны фиксированный candidate, exact CI и fresh-image проверка. Report gate300ms не менялся: локально144,5ms и CI207 shard3 GREEN; product fix не было. Режим только Mock; существующие PITCH/DEMO не изменены.

До выхода оператор на собственной synthetic копии штатно готовит два counters run:

- `POST /api/scenarios/csi_and_branches/run`, JSON `{"label":"Freeze demo: CSI and branches","reset_mode":"counters","seed":42}` → **C**. Paused clock неизменен; effective main/fast/twin Mock. 301 вход = 300 registered sample / 2400 visits + 1 extra uncohorted/unknown. Exact source-ID set = 301 primary agent AR.signal_id, active/failed/missing/duplicates0. Дождаться вне таймера: только mass preparation имеет120s/hook150s; UI/product deadlines не меняются.
- `POST /api/scenarios/cabinet_red_words_report/run`, тот же reset_mode/seed и отдельная label → **K**. Два native входа: legal red-word **pending HITL** и отдельный ordinary deposit route. Никаких HD accept. Current становится K; все вкладки фиксируются числовыми C/K. Clock не двигать.

Не использовать numeric scenario14/15: новые named cases имеют catalog34/35, старые1..33 сохранены. DemoMenu не содержит их кнопок. Не reset baseline между блоками.

## 5 минут

- **0:00–0:30.** Рамка: «Синтетический банк, редакционный baseline и новый native run. Сейчас Mock, не настоящая LLM». Mode badge виден; C/K названы.
- **0:30–1:30.** `/csi?run_id=C&period=month`, preset `cx_lead`, без направления. Жалобы/scatter/sample. «300 наблюдений / 2400 визитов; дополнительное обращение не добавляет знаменатель. Корреляция синтетическая, неизвестное не ноль».
- **1:30–2:15.** `/workspace?tab=map&run_id=C`, кнопка «ВСП», 7 дней, cluster → карточка. «Прямое N этой ветки — не city90-day count». Branch Trace не входит в основной показ: правильный PK в ссылке не делает generic карточку полным адаптером T233. Далее используем доказанный native Signal Journey/Trace. Окно Map week не выдавать за month CSI.
- **2:15–3:30.** `/cabinet/deposits?run_id=K&period=week`, `product_manager`, binding deposits. «Только красные слова» → legal case. **STOP: ждёт человека.** Снять фильтр, показать ordinary input как отдельное доказательство route. Роли — пресеты, не auth.
- **3:30–4:15.** `/cabinet/deposits/report?run_id=K&period=week`: выводы, unknown и XLSX. Только при зелёном неизменном gate300ms на выбранном candidate. Fallback — подписанный source/run export как файл, не live GET.
- **4:15–5:00.** `/journey/<actual-SIG>?run_id=K&mode=presenter` → actual step/client lane/Trace. «Показываем сделанное и ожидаемое; pending не completed». Никаких кликов accept/refund/gift.

## 8 минут

Тот же набор с большим временем на доказательства:

- 0:00–0:40 рамка; 0:40–2:00 CSI + альтернативная таблица и sample/unknown.
- 2:00–3:10 Map + co-located список/keyboard + четыре блока аналитики.
- 3:10–4:50 Cabinet: ordinary route отдельно от legal pending, отчёт/XLSX.
- 4:50–6:10 optional «Новый сигнал»: chat, выбранный synthetic mass клиент, ordinary текст existing YAML; один submit → фактические SIG/AR/«Показать путь». Это **новая write-фаза**, а не read-only навигация. Только если отдельно пройдена на финальном source; иначе открыть подготовленный SIG и прямо назвать его записанным входом. Не обещать завершение за X секунд.
- 6:10–7:20 `/clients/<actual-client>?run_id=K` → «Уведомления клиента»: клиент/run сохранены. Показать только реально Sent этого клиента в K; empty честно оставить либо заменить блок read-only графом. Чужой/baseline подарок и pending gift не подменяют ни Sent, ни факт выдачи. Снять client filter — явное действие, run остаётся K.
- 7:20–8:00 Presenter Journey/Trace и ограничения.

## Красные линии

- Нет T020 native14day/Fact/empirical retention/реального ROI; seed labels не native AR и не реальная история клиентов.
- Нет real LLM/TG/email/cloud STT/микрофона/новых cassette recordings. Неподходящий replay hash не rekey; Journey presenter — read-model, не provider replay.
- 409/500/нет AR: сохранить ошибку, остановить блок. Не All ради красивого результата, не clock/reset/SQL/status fix. При здоровом GET и потерянном WS можно reload того же URL.
- Только source-labelled backup PNG/exports; озвучить, что это запись. Не переключать env/provider и не запускать install во время показа.

Репетиция пока **not_measured**. До общего фриза на фиксированном candidate: одна 5-min и одна 8-min попытка с wall-clock, exact IDs и request errors; записать реальные задержки и отклонение. Подробный [preflight, источники и fallback](reviews/DEMO-FREEZE-2026-11-03-preflight.md). [Manifest репетиции](reviews/DEMO-FREEZE-2026-11-03-manifest-template.json). Все actual durations пока `not_measured`. Existing [DEMO.md](DEMO.md)/[DEMO-SCRIPT.md](DEMO-SCRIPT.md) сохранены как прежний вариант. Этот пакет не закрывает критерии T204/T260/T154 без репетиции и не меняет PITCH PR176.
