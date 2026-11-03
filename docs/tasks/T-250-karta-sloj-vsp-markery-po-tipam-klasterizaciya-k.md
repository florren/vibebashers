# T-250 — Карта: слой ВСП (маркеры по типам, кластеризация, карточка), тихая метка закрытых, блок «ВСП vs Сигналы»

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Map` (карта РФ) |
| Оценка | L (3–4 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
ЕТЗ 5.4, 8.2–8.4 и критерии 16.1 (ТЗ 25.5) на существующей карте d3-geo.

## Разделы ТЗ (docs/TZ.md)
§25.5, §25.4, §12.2

## Контракты
- `api/openapi.yaml: /api/branches/*`
- frontend/src/pages/workspace/MapTab.tsx

## Зависимости
- Зависит от: [T-248](T-248-api-analitiki-csi-i-vsp-korrelyacii-scatter-dolz.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md), [T-245](T-245-spravochnik-vsp-v2-rasshirenie-branches-generato.md)
- Блокирует: [T-262](T-262-scenarii-14-kabinet-menedzhera-krasnye-slova-i-o.md)

## Что сделать
1. Слой ВСП в отдельной группе под слоем сигналов; включение одним щелчком; маркеры по типам и цветам из ТЗ 25.4; кластеризация при малом масштабе, чтобы не перекрывать сигналы.
2. Карточка ВСП (адрес, режим, сигналы, CSI-метрики, ссылка на `/trace/branch/{id}` (выданный PK, отображаемый code сохраняется)); закрытое ВСП с сигналами — тихая метка «закрыто · N сигналов».
3. Блок «ВСП vs Сигналы»: тепловая карта «сигналов на 1 ВСП», список регионов с дефицитом, график динамики сети (12 мес.), таблица сигналов в зонах закрытия с фильтром.
4. Данные ВСП кэшируются на клиенте (TTL 24 ч); менеджер направления видит только свои ВСП; vitest и e2e.

## Критерии приёмки
- [ ] Слой включается и выключается одним щелчком; маркеры не перекрывают сигналы (визуальная проверка).
- [ ] Закрытые ВСП с сигналами помечены тихой меткой; блок содержит четыре метрики ЕТЗ 8.4.
- [ ] Карта загружается ≤ 3 с на demo.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/workspace/map
cd frontend && npx playwright test e2e/map-branches.spec.ts
```

## Отчёт субагента
Ветка `codex/T-250-map-branches`; обычная композиция clean API29c8/T255192/Journeyc463. Lazy directory/real-coordinate clusters/list/keyboard/card/4аналитические метрики; direct closed counts отдельно от city90-day proxy. Map-only current/read-only граница выставляется до legacy KPI mount, other tabs defaults сохранены. API30 additive RunId/оба aliases/422; все155API29 и167API28 DTO без изменений.

Fresh demo5000/600000operations +actual XLSX301→300members/2400visits: native4/4 ru/en×themes, final initial298–321ms, все branch/analytics/count reads729–754ms,97tablehashesunchanged,0external/nonGET/errors. Новый self-prepared e2e4/4 (8.5s), missing-marker refusal сохраняет97hashes/current; CI marker только test environment. strict map-layout20/20 sourcef98, glyph-specific4unit/native4green. `make lint` exit0:512front/74files,backend557/325,bot12/5,drift196/196; production main/personal build и contracts green. Ранние6PG scope/alias cases source731/0387; не выдаются за full finalhead. Visual follow-up проверен: count ниже anchor18CSSpx, neutral ring transparent, нет пересечения/clip при прежних координатах/aria/listN. Нужны exact-head full CI и human contract review, статус остаётся in_progress. [UI/proof](../reviews/T-250-ui-candidate.md), [API30review](../reviews/T-250-api30-review.md), [machine evidence](../reviews/T-250-native-proof.json).
