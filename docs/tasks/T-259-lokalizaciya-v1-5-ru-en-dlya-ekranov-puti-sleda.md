# T-259 — Локализация v1.5: ru/en для экранов пути, следа, кабинета, CSI, обзора; подписи enum; проверка полноты

| Поле | Значение |
|---|---|
| Эпик | E13 Локализация |
| Субагент | `SA-i18n` (локализация) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 9 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Все новые тексты — через i18n (правило 9), словари полные.

## Разделы ТЗ (docs/TZ.md)
§12.4, §26.3

## Контракты
- frontend/src/shared/i18n/ru.json, en.json
- `backend/app/i18n/`

## Зависимости
- Зависит от: [T-226](T-226-ekran-put-obrascheniya-journey-ref-stepper-iz-8.md), [T-232](T-232-ekran-sled-trace-kind-ref-do-obekt-posle-itog-oz.md), [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md), [T-249](T-249-ekran-csi-csi-tablica-zhalob-scatter-bar-po-dolz.md), [T-254](T-254-karkas-v2-bokovaya-navigaciya-sostoyanie-sistemy.md)
- Блокирует: —

## Что сделать
1. Ключи по экранам, подписи перечислений (`trace_event_kind`, `journey_stage`, `product_line`, `signal_level`, типы ВСП), «тёплые» формулировки пустых и ошибочных состояний.
2. Тексты событий следа и путей на стороне backend (`app/i18n`) для заголовков и описаний; проверка отсутствия «сырых» ключей.
3. `make i18n-check` зелёный, словари синхронны.

## Критерии приёмки
- [ ] `make i18n-check` зелёный; в UI нет «сырых» ключей на обоих языках.
- [ ] Заголовки событий следа локализованы на языке интерфейса.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make i18n-check
cd frontend && npx vitest run src/shared/i18n
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
