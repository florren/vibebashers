# T-203: актуальные ru/en экраны

Production build Vite, Chromium1217, source composition `c4d4d0a366246fe96691b484111f527a5a252e67` после ordinary merge main2ed39d2.
Собственная PostgreSQL16 cx_t203_i18n_revision, baseline200клиентов иреальный
корпусный scenario09_isj через Mock. Englishlabels/Branch0042/Employee
проверены Playwright. Цитаты, synthetic employee и summary_ru — сохранённые
данные источника, не переводились и не подменялись.

12desktop сочетаний ru/en ×light/dark ×feed/manager/compliance и2English
Manager320×320 (full-page capture). Здесь14PNG (12desktop ru/en и2узких English); полный proof
в docs/reviews/T-203-browser-proof.json, исходные PNG также сохранены в /tmp.
320px — проверка узкого viewport, не приёмка отдельного UI смарт-часов.

QA preview: APP_ENV=test, штатныеAPI/production bundle, Simulator загружен
изреального sim_state в READ ONLY транзакции без запуска ticks/actors.
ProviderChain.complete_structured заменён Bomb,0calls; все внешниеrequests
и HTTP mutations блокированы,0attempts. Отпечатки85publictables до/после
совпали. APIentityresponses не замоканы. Это проверка локализации, не liveLLM.

Новый composed QA повторён после main2ed39d2. Исходная QA-БД не пересидировалась; отдельные PG template tests используют cx_t203_compose_revision. Full make test77fd — исторический source-specific результат, который не выдаётся за новый полный прогон. Представительные новые feed/manager/compliance кадры и320px просмотрены: локализованные подписи читаемы, цитаты/summary_ru остаются данными источника.
