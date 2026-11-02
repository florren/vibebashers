# T-248: закрытие двух найденных network defects

Read-only reviewer на source65a83c9 подтвердил два P2 actual PostgreSQL oracle: UTC session ломала Moscow-local month series, а legacy NULL branch_status/closed_sim выдавались за известныеopen1/closed0. Изначальные proofs сохранены рядом; это реальные ошибки, не flaky tests.

Native API regression до исправления дал1failed9.48с: вторая метка2025-12-31 вместо2026-01-01. Отдельный unknown regression дал1failed9.02с. Assertions не ослаблялись.

Исправление строит generate_series по timestamp WITHOUT time zone первого локального дня месяца. Каждая локальная start/end граница отдельно переводится через Europe/Moscow в timestamptz; session timezone не меняется. При неизвестном current status и отсутствующей closed date open/closed history остаётсяNULL, как pressure. Известная дата закрытия может сохранять историю известной даже при unknown current status; opened_in_month зависит отдельно от известной даты открытия. Пустой выбранный directory subset остаётсяструктурным0.

После исправления10native branch/directory/baseline tests passed68.32с, включая все12month labels и независимые Dec/Jan/Feb/Mar expected counts: открытия поздно31числа, закрытия ровно00:00следующегомесяца и23:59:59.999999последнего дня. Старые stored-global history и roundtrip guards сохранены. Supporting test zip получил strict=True; production literals ещё отдельно пройдут coverage/native scoped performance. Full unit/core/CSI evidence65a остаётсяsource-qualified предыдущим этапом, не объявляетсяновымполнымпрогоном.

API28/DDL20 human review и exact-head CI ещё впереди. Shapes/лимиты/формулы/банковскиеpolicy/операционные данные не менялись; networknullable semantics соблюдены по исходному контракту.
