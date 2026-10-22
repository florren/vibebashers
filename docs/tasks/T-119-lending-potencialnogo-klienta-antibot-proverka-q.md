# T-119 — Лендинг потенциального клиента, антибот-проверка, QR

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-Landing` (лендинг и трекинг) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Экран 6: форма обращения для неидентифицированного клиента с выдачей ссылки трекинга и QR.

## Разделы ТЗ (docs/TZ.md)
§11.2, §12.2 экран 6

## Контракты
- `api/openapi.yaml: public/claim, public/captcha`

## Зависимости
- Зависит от: [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md)
- Блокирует: [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md)

## Что сделать
1. Страница /landing в стиле ТЗ 12.1 без брендирования: описание, форма (контакт, регион/город, продукт, текст, согласие), арифметическая captcha, лимит 5 обращений/мин с IP.
2. Backend: создание сигнала origin=landing с external_contact, tracking_token (secrets.token_urlsafe(24)), QR SVG (python qrcode) ссылки трекинга.
3. Экран успеха с public_id, ссылкой, QR и кнопкой «Открыть трекинг».

## Критерии приёмки
- [ ] Сценарий 4 через лендинг проходит до ответа.
- [ ] Без captcha/согласия — 422 с понятным текстом.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/landing.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
