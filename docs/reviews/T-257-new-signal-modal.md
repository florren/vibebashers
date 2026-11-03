# T257: новый сигнал и явный выбор STT

## Реализовано

Прежний `POST /api/signals` и нормализатор сохранены. Модал содержит канал, известного/неизвестного клиента, ручной client ID, город из настоящего справочника, текст, подсказки маршрутизации/ПДн и карточку результата. Journey использует настоящий public ID, Trace — настоящий signal ID; неполный ответ не создаёт вымышленные ссылки. Unicode codepoint validation 3..5000 не обрезает ввод. Label textarea отделён от VoiceInput, результат доступен через status. Один стабильный JuryModal sibling в Header сохраняет форму/результат при смене desktop/mobile; старый remount воспроизведён actual browser, защищён двумя unit-регрессиями и неизменённым строгим resize-переходом e2e.

VoiceInput требует native `isSecureContext` и допустимый HTTPS/loopback origin, в том числе не обходит небезопасного ancestor. Browser voice_meta содержит только фактически известные финальные транскрипты/provider; длительность аудио, latency, model и средняя confidence не выдумываются. PCM duration для серверного пути считается по фактическим байтам прежним способом.

## Privacy / API31 — конкретная граница review

Ранее `STT_PROVIDER=none` без модели неявно выбирал внешний browser; VoiceInput также выбирал browser при пустом/ошибочном списке. Теперь автоматический выбор допускает только доступный offline Vosk, иначе default отсутствует. Явный недоступный Vosk также не подменяется. Явный `browser` через конфигурацию/API/dropdown остаётся opt-in, с видимым внешним предупреждением до start. LiveMeeting сохраняет явный выбор при refetch, показывает placeholder и блокирует start без проверенного доступного provider. Неоднозначные defaults, ошибка и пустой список fail closed; `serverOnly` не разрешает browser. При потере проверки активный browser прекращается через abort без приёма позднего текста.

`registry.default_code()` теперь `str | None`; все существующие callers проверены. API отвергает отсутствие выбора до чтения PCM/файла и создания compliance session. Единственный contract delta поверх API30: `info.version=1.5.31`, существующий `422 Problem` для `/api/stt/test`. Все components/paths/DTO, успешные ответы и остальные операции сохранены; строгая структурная equality проверена. DDL, деньги, HITL, роли и auth не менялись.

Rollback: возврат UI/registry commit возвращает прежний нежелательный browser fallback, поэтому предпочтителен forward fix. Схемы/данные не мигрируются; existing explicit browser остаётся совместимым. API30 Map dependency обычным merge59e765b, API29/CSI/receipt зависимости сохранены.

## Финальная проверка source48fb40f

- `make lint`: 555 frontend tests /79 files; frontend eslint/motion/typecheck,558 Python format files, mypy325, bot12 format/5 mypy, OpenAPI drift196/196 — EXIT0.
- Обе production builds (`main`, `personal`) — green.
- 15 backend unit/ASGI HTTP tests: default selection, explicit browser opt-in, 422 Problem до PCM/файла/DB; 49 adjacent frontend до композиции Map, затем весь555 suite на композиции.
- Настоящая PG fake-STT file audio session:1 passed10.30s в собственной cx_jury_ui_revision. Реальный Vosk/audio model не запускался. Registry functional coverage89% (32/36 statements), отдельно от timing.
- Production Chromium:5/5,7.4s, без retry, стандартный30s timeout. Четыре настоящих POSTsignals202, сохранённый city/client, Mock agent steps, Journey8stages и Trace200; ru/en×light/dark, desktop1440 и mobile360. Native insecure origin через Chromium loopback resolver: микрофон скрыт, текст доступен. Реальные mic/media/STT/external calls0; неожиданные application writes0. Ожидаемые POSTsignals4 и setup/restore UI settings не выдаются за read-only DB proof.
- 13 PNG в `docs/screenshots/T-257`; просмотрены desktop ru/light, mobile en/dark result и ru/dark top: текст/controls читаемы, overflow guard green. Машинные source/result/hash — `T-257-proof.json`.

Исторические498/516 frontend и первые actual resize failures относятся к предыдущим source и не выдаются за финальные проверки. Сохранённый локальный failing evidence `/tmp/t257-browser-first.log`, первый output directory `/tmp/t257-browser-results`; final — отдельные файлы. Полный backend `make test` на этом новом API31 source не повторялся: изменённая STT граница покрыта unit/HTTP/PG, общий full/exact-head CI ещё обязателен. Реальные mic/STT и качественная проверка распознавания намеренно не выполнялись. Карточка остаётся in_progress до parent review/CI и полного DoD; T206 целиком этим PR не закрывается.

## Root: финальная композиция

Runtime05f6969 обычными merge включает final Map4516 (runtime d1fc),
T262 test compatibility05ee и metadata PR204. API31, JuryModal/Header/VoiceInput/
LiveMeeting/STT registry побайтно совпадают с проверенным27a3; numeric Trace links
и metadata относятся к проверенным родителям. Public runtime OpenAPI теперь
объявляет canonical1.5.31.

Root28backend targets GREEN2.81s (STT/metadata/source contract), Ruff560/mypy326,
bot12/5, drift196/196; полный frontend **556/79files** GREEN. Штатный `npm run build`
успешно собрал main и personal. Первоначальная shell-проверка дополнительно вызвала
несуществующий alias `build:personal` после успешной штатной сборки; её failed log
сохранён, затем только правильный `npm run build` повторён успешно. Это command
correction, source не менялся.

Прежний actual production browser5/5 и13PNG source-qualified для неизменённых
Jury/STT/resize компонентов; повторным browser run нового wholehead не называется.
Final Map имеет собственный новый image proof родителя. Полный exact-headCI
и интеграция вmain остаются обязательными.
