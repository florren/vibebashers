# T-203: английские экраны

Production build Vite, Chromium1217, source main1df0024 +T203workingdiff.
Собственная PostgreSQL16 cx_t203_i18n_revision, baseline200клиентов иреальный
корпусный scenario09_isj через Mock. Englishlabels/Branch0042/Employee
проверены Playwright. Цитаты, synthetic employee и summary_ru — сохранённые
данные источника, не переводились и не подменялись.

12desktop сочетаний ru/en ×light/dark ×feed/manager/compliance и2English
Manager320×320 (full-page capture). Здесь8EnglishPNG; полный proof
в docs/reviews/T-203-browser-proof.json, ruPNG сохранены в /tmp.
320px — проверка узкого viewport, не приёмка отдельного UI смарт-часов.

QA preview: APP_ENV=test, штатныеAPI/production bundle, Simulator загружен
изреального sim_state в READ ONLY транзакции без запуска ticks/actors.
ProviderChain.complete_structured заменён Bomb,0calls; все внешниеrequests
и HTTP mutations блокированы,0attempts. Отпечатки85publictables до/после
совпали. APIentityresponses не замоканы. Это проверка локализации, не liveLLM.

Первый QA script остановился на неверном selector роли/названия вкладки;
после исправления selector прошёл. Первый fingerprint script имел missing
Path import; только успешный повтор с BEFORE/AFTER считается доказательством.
