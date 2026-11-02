# T262: native Mock product direction prerequisite

На исходной композиции API28 + T244 native identified complaint «вклад / суд / налоговая» дала product=deposit, product_line отсутствует, high/red_words, awaiting_human/legal_regulatory, один pending human_decision и ни одного incident/route facade. Это actual graph, не подмена LLM output. Существующий optional product_line enum не допускает JSON null: неизвестное направление остаётся отсутствующим в mock structured output и NULL в consumer projection.

По техническому signoff root Mock дополняет только однозначный product→line из canonical product_lines.yaml через существующий loader. Immutable cached mapping не уточняет coarse credit и не угадывает unknown. Real provider, JSON schema, routing/HITL/денежные политики не менялись. Usage сохраняет явный provider/source=mock.

После исправления тот же native pipeline сохраняет product_line=deposits, high и pending legal HITL; автоматического human accept или executed product route по этой жалобе нет. Для T262 обычное отдельное deposit обращение проверит actual route_to_product_team; single-arrow требование требует явного acceptance review до закрытия карточки. Не выдаём planned route за исполненный.

Проверки:4 новых schema/provider unit; вместе с исходными Mock/normalization/catalog/HITL/product-facade regressions **96 passed,20.31s** (`/tmp/t262-mock-canonical-regression.log`). Probe выполнялся на собственной cx_scenarios_262_revision с APP_ENV=test/LLM_PROVIDER=mock; реальные внешние вызовы и production отсутствуют. Финальные сценарии/UI/replay этим checkpoint не закрыты.
