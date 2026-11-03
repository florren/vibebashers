# T-262 — native UI кабинета, CSI и recorded Journey

Завершена офлайн Mock UI-приёмка на неизменном application source40db068,
побайтно равном backend/contracts/frontend-src837eec6. Использованы настоящие
production assets T0926f0668e; бизнес-API/ответы не подменялись, моделей live нет.

## Два независимых прогона

1. Сохранённые C5/K6:9/9passed15.921s, APP_ENV=test с загруженным paused Simulator,
   actors выключены, PG default_transaction_read_only=on. Все97 public table
   fingerprints неизменны; HTTP browserwrites/externals0. Это отдельный readonly
   harness, не запуск production actors. Legal HD196 сохранился decisionnull.
2. Default-путь нового E2E самостоятельно создал C7/K8 через штатные scenario API,
   без заранее переданных run IDs.9/9passed52.946s. Здесь preparation ожидаемо
   пишет в свою synthetic БД, whole-bank-readonly не утверждается. Native C7:
   301signals/301primaryAR,300members/2400visits/10cohorts +1uncohorted; K8:
   2signals/2primaryAR. После остановки своих actors active0/failed0; HD262null,
   старый HD196 тожеnull. Clock paused/не изменён, роли main/fast/twin Mock.

Матрица ru/en×light/dark:7 блоков кабинета, legal red stripe/слова/readonly drawer,
отдельный ordinary route_to_product_team→team_deposits, rate961 на сервере,
сценарное affected1000000 с явной пометкой; XLSX через настоящий download.
9 блоков CSI,301/300/2400,top10,корреляции/таблицы/chart alternatives; закрытое
ВСП с прямым N и unknown denominator. Читается C7 при currentK8, ссылки несут
свойrun/branchPK. Desktop/mobile проверены,37PNG в screenshots/T-262-native.
Все четыре XLSX отдельно распакованы: оба ожидаемых SIG присутствуют в XML.

Recorded Journey читает actual Mock history:16 кадров,3 с настоящей Mock source
меткой. Конец остаётся waiting_human, human decision не принимается. Это не LLM
cassette replay. Первый RED8/1 требовал Mock на последнем human frame; тест теперь
проверяет источник на LLM кадрах по реальным event titles и pending boundary в конце,
не заставляет интерфейс ошибочно маркировать human как Mock.

Новый тест регистрируется в serial scenarios project; подготовка ограничена120s
poll/150s hook, UI30s. Предыдущие actors действительно ожидаются до active0, не
сбрасываются. Mobile resize ждёт устойчивую раскладку до1s. Strict TypeScript
прошёл; новые dependencies/API/DDL/денежные/HITL правила не вводились.

[Machine proof](T-262-native-ui-proof.json). Whole T262 остаётся in_progress:
согласованные реальные новые cassette responses и пункты DemoMenu не получены.
Имеющийся script/doc freeze честно указывает эти ограничения.5/8минутный устный
хронометраж ведущего этим техническим прогоном не проверялся. Общий exact-head CI
нового E2E и его интеграция с lifecycle Jury ещё обязательны.
