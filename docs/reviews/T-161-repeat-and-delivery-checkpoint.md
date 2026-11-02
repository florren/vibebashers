# T-161 — repeat/delivery checkpoint

Root technical signoff реализован: signal-only repeat не требует фиктивной
operation. Known canonical type/product используют существующий T-019;
unknown product повторяет actual parent text с явным text_source=parent_signal.
Канал выбирается по утверждённым weights. Новая normalizer запись имеет origin=sim
и только разрешённый model provenance; telegram_chat_id/delivery grant из parent
metadata не переносятся, реальные transport bindings не создаются.

Care speed и repeat используют одну eligible_reply границу. Repeat дополнительно
проверяет native run/client/episode, received_sim и sent_sim<=deadline. Старый
parent ack в paused clock не обслуживает новый child с тем же SimTime; допустим
new direct child ack либо incident-only notice с подтверждённым creation order.
Queued/unknown/failed/future/gift/DM/invalid/foreign/unrelated не считаются ответом.
Probabilities/weights не менялись. Receipt на actual repeated signal объединяет
Twin observation, parameter timer и canonical child classifier: один факт не
увеличивает repeat_count дважды. Satisfaction остаётся observation, не care.
Existing churn_intent не сбрасывается новым unresolved message; same-state care
updates не публикуют новый retained/churn_intent факт повторно.

5 actual PG tests passed28.73s: known/unknown repeat с новым connection, 13-case
reply matrix, actual FakeMock Twin→canonical child dedup и same-tick old/new ack,
resolved episode reopen без переноса старого care. Прежний fullunit phase был
1705 passed/18 skipped46.78s с явной own DB; итоговый suite ещё нужен после всей
composition/activation. До правильной настройки первый unit run завис после8
тестов и остановлен только свой pytest; incomplete run не считается проверкой.

OS-process proof до последних repeat edits отдельно дал1pass21.99s: собственный
native PG16 reference clone, uninterrupted control и SIGKILL+fresh process.
Semantic events/signals/states/timers/receipts/clock/RNG exact. Единственная
root-approved normalization — declared real-time review.posted.posted_at; native
равенство/aware/wall-run bounds проверены, raw event hashes раздельны. Этот proof
обязательно повторяется на окончательном source, старый артефакт pytest temp не
выдаётся за immutable final evidence. Native generated failure single-owner и
signal-only all-causes care/resolution отдельно2PGgreen21.31s.

Runtime packet enabled=false в этом checkpoint. Далее coherent activation,
контроль legacy admission до resume/graph effects, final merge P1/main/T121 guard,
full suite/changed-line coverage/archive/baseline и повтор OS proof. Не done.
