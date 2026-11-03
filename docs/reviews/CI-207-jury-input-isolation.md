# CI207: Jury-ввод выполняется после проверок read-model

На head4107a013 все четыре backend-shard, frontend, lint, contracts, DB и image
build прошли. E2E207/209 выявили один оставшийся недетерминированный Overview
snapshot: отдельный API probe видел saved202.88/CXunknown, затем настоящий UI
видел205.17→410.34/CX100. Источники — native обращения предыдущего Jury-теста;
их последующие фоновые эффекты продолжаются после завершения самого POST.
Предыдущее отделение только массового Map preparation не изолировало Jury.

Пять существующих Jury cases вынесены из settings в последний serial inputs
project. Порядок: read-only58 → settings88 → scenarios4(Map) → inputs5(Jury).
Это не задержка ожидания, подмена данных или допуск суммы: остаются те же155
case identifiers, все точные assertions, retries0, UI30s и прежний300ms gate.
Последующий native ввод больше не может менять снимки предыдущих read-model
проверок. Никакие runtime/API/DDL/денежные/HITL правила не менялись.

Проверка multiset IDs CLI --list:155→155, omitted0/duplicates0. Свежая полная
сборка штатным backend/Dockerfile прошла; затем отдельный disposable Compose
прошёл155/155 за5.7min. Overview8, Map4 и Jury5 реально выполнены в новом
порядке. Source app —4107a013; отличие только playwright.config.ts. Реальные
LLM/STT/Telegram/email не включались. Helpers удалили собственные volumes/network;
пользовательский стенд не запускался. Node22.23.4 совпадает с CI. Локальная первая
установка Chromium подNode26 зависла и остановлена, установщик подNode22 завершён;
это не объявляется изменением продукта или доказанной причиной Node26 бага.

Сгенерированные20 PNG старых тестов сохранены внеGit и возвращены побайтно кHEAD,
исходно до запуска они не были изменены. Exact-head requiredCI нового commit
остаётся обязательным до merge. [Safe proof](CI-207-jury-input-isolation-proof.json).
