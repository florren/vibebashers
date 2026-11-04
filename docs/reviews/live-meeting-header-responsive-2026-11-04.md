# Мобильный заголовок микрофонной встречи

Дополнение к `live-meeting-closed-status-2026-11-04.md`: обнаруженное там обрезание
controls на 320px исправлено локально. Shared Section уже переносит элементы
заголовка, но вложенный right-контейнер LiveMeeting оставался nowrap с intrinsic
minimum width. Его `min-w-0 max-w-full flex-wrap` позволяют перенести модель,
public ID и Close внутри карточки. Общие styles и shared Section не меняются.

До исправления actual Chrome при viewport 320 показал Close x=296.09, width=80.86,
right=376.95: кнопка обрезана. После исправления production bundle проверен
на 320/1440 × ru/en × light/dark: вся кнопка внутри viewport, документ без
горизонтального overflow. Close disabled во время live, enabled после matching
server closed; настоящий клик закрывает панель. Badge closed и счётчики сохранены.
Проверен keyboard focus. Реальные PCM/WS/Vosk/GET сохранённой сессии используются
с прежним фиксированным synthetic WAV в Chrome fake microphone, не физическим mic.

10 component tests проходят (новый regression запрещает callback Close до server
closed и разрешает после); ESLint и production build с TypeScript проходят.
Полный предыдущий набор 589 был зелёным до этого локального CSS дополнения;
повтор полного набора здесь не выполнялся. Стандартный DemoMenu react-refresh
warning не относится к изменению. Backend/правила/ledger/audio I/O не меняются.

Machine evidence: `live-meeting-header-responsive-evidence.json`.
Приватные actual screenshots и logs: `.runtime/freeze-live-meeting-responsive-*`.
Откат — вернуть одну className и удалить новый component regression; DB не меняется.
