# data/ — справочники, корпуса и сид

Все данные синтетические: имена, ники, номера карт (`card_last4` — невалидны по Луну), отзывы и диалоги сгенерированы.
Партнёры в `gifts.yaml` вымышленные.

| Файл / папка | Что | Источник |
|---|---|---|
| `federal_districts.csv`, `regions.csv` | 8 округов, 89 субъектов РФ: код (КЛАДР/ФИАС), названия, население (оценка, тыс. → чел.), условный центроид (= координаты адм. центра, пока нет SVG-карты) | составлено вручную |
| `cities.csv` | 1 121 город: регион, население, координаты, признак адм. центра | [hflabs/city](https://github.com/hflabs/city) (CC BY-SA 4.0), поля сокращены; добавлены центры новых субъектов |
| `segments.yaml`, `psychotypes.yaml` | сегменты (ТЗ 3.1) и психотипы с параметрами по `behavior/psychotype_params.schema.json` (ТЗ 4.5) | ТЗ |
| `products.yaml`, `systems.yaml`, `teams.yaml`, `channels.yaml` | продукты/тарифы/акции, 12 систем, 12 команд с профилями скорости, 11 каналов | ТЗ 3.3–3.6 |
| `product_lines.yaml` | 15 продуктовых направлений кабинета менеджера: `rate_code` → `dcltv_rates.csv`, команда-владелец, доли демо-отзывов (54 всего) | ТЗ 24.2 / ЕТЗ; данные синтетические, без брендов реальных банков |
| `error_codes.yaml` | коды ошибок (`PROC-QR-FEE-CHARGED` и др.) и типы сигналов | ТЗ 4.2, BRD |
| `sla.yaml` | матрица SLA 3×3 и правила маршрутизации | ТЗ 8.1–8.2 |
| `gifts.yaml`, `dcltv_rates.csv` | каталог извинительных подарков, экономические настройки, ставки dCLTV | ТЗ 8.5, 14 |
| `tariffs.yaml`, `rules.yaml` | тарифы Mock-АБС и бизнес-правила (`RULE-QR-FEE-001`) | BRD |
| `misselling_patterns.yaml`, `service_scripts.yaml` | паттерны misselling/conduct с примерами, эталонные скрипты | ДТЗ 22.4, 22.8 |
| `branches.yaml`, `ingest_sources.yaml`, `llm_profiles.yaml` | 10 ВСП × 6 сотрудников (ВСП № 0042 Самара — сценарии 9/10), адаптеры, профили LLM | BRD, ТЗ 3.7, 5.2 |
| `templates/notifications.yaml` | Jinja2-шаблоны уведомлений по сегментам | ТЗ 8.4 |
| `scenarios/*.yaml` | 11 демо-сценариев | ТЗ 18 |
| `corpus/signal_templates.yaml` | шаблоны текстов сигналов 10 типов × 4 продукта + сарказм/сленг/опечатки | — |
| `corpus/mock_feed.yaml` | 30 постов mock-ленты соцсетей/отзывов (сценарии 8, 11) | — |
| `import/transcripts/` | 20 транскриптов (10 JSON по `ingest/transcript.schema.json` + 10 TXT), `scenario10_retail.txt` | `scripts/seed/gen_corpora.py` |
| `bench/*.jsonl`, `bench/transcripts_v1/` | sentiment_v1 (300), hidden_negativity_v1 (120), summary_v1 (60), red_phrases_v1 (139), golden_v1 (120), эталоны транскриптов | `scripts/seed/gen_corpora.py` |
| `cassettes/` | записи LLM для офлайн-replay | — |

## Шрифты UI (T-263)

Бинарники Inter (400–700, latin + cyrillic) и JetBrains Mono (400, 500) лежат в `frontend/public/fonts/` (формат woff2).
Источник: официальные релизы [Inter](https://github.com/rsms/inter) и [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono), лицензия OFL 1.1 (`docs/LICENSES.md`). В рантайме внешние CDN не используются.

## Сид

```bash
python scripts/seed/run.py --profile lite|demo|stress [--seed 42] [--reset-history] [--refs-only]
```

Идемпотентен: справочники — upsert по коду, клиенты и история создаются один раз (`settings.seed_done`).
Профили: lite 1 000 клиентов / 800 сигналов / 150 инцидентов; demo 5 000 / 2 500 / 400; stress 20 000 / 10 000 / 1 500 (ТЗ 4.4).
После сида считается матрица покрытия (`settings.coverage`): каждая комбинация тип × продукт × канал ≥ 1 сигнал, каждая ячейка SLA ≥ 5 инцидентов
в разных статусах, доля «трудных» текстов (сарказм/сленг/опечатки/капс) ≥ 25 %, 3–5 % операций card_payment/qr_sbp с `PROC-QR-FEE-CHARGED`, у 60 % клиентов `social_handles`.
История пишется в `sim_runs` kind=`baseline` («История 14 дней (сид)»); `sim_state.current_run_id` указывает на неё, пока симулятор не создаст новый запуск.
