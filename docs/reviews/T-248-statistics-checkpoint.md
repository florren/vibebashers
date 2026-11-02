# T-248: проверенное математическое ядро, API ещё не реализован

Добавлены внутренние функции Spearman с average tied ranks и pairwise complete
finite observations, и quartiles по linear interpolation R7. Constant series и
n<2 дают неизвестный coefficient, пустой ряд — неизвестные квартили. Missing,
NaN, infinity и bool не превращаются в ноль; рядом возвращается число пригодных
observations. Для корреляции bucket probability n означает число корзин,
а не число визитов и не доказательство индивидуальной причинности.

Проверены20 unit/actual-PG cases,2,14с. PostgreSQL READ ONLY запросы независимо
сравнили квартили с percentile_cont и tied Spearman с corr средних window ranks.
Покрытие модуля52/52 statements; Ruff/format/mypy модуля прошли. Никаких новых
зависимостей, API, DDL, write effects или внешних сервисов в этом checkpoint нет.

## Следующий пакет — непроверенный проект

До реализации API28 требуется run/cohort provenance знаменателей. Исходная
csi_visits_agg не хранит происхождение; существующие данные нельзя объявлять
baseline либо current по догадке. Предпочтительный additive путь: отдельные
cohort + signal membership + visits tables с собственным run, window, synthetic
marker и проверенным digest набора. Legacy csi_visits_agg сохраняется без
переписывания и остаётся unknown для вероятностей. Конкретная DDL20 ещё не
создана; receipt0019/API27 принадлежат отдельному T-039 child.

Регистрация корпуса должна использовать normalizer для всех signals, проверять
все native accepted payloads/CSI IDs/run/branch/staff и атомарно сохранять
знаменатели. Совпадения одного CSI ID недостаточно: иной payload/другой run
не должны получить denominator. Повтор exact cohort идемпотентен; частичная
или неизвестная когорта остаётся unknown, а не известным нулём.

API читает один MVCC snapshot, явно возвращает run/filter/period/coverage.
Числители жалоб без подходящего знаменателя показываются отдельно; их нельзя
включать в rates с другим denominator. Strict scope использует разрешённые
продуктовые направления и фильтрует numerator и denominator одинаково.
Employee box plot не раскрывает имён и отличает anonymous complaints от реально
известных сотрудников без жалоб. Branch directory/history — отдельный global
catalog snapshot с явным происхождением, без обещания исторической версии
каталога для arbitrary run. Threshold дефицита отделений без утверждённой
настройки неизвестен; новые значения не выдумываются.

Это план, не реализованный контракт. API/DDL и определения coverage получат
отдельный final human review после конкретного diff и actual-PG проверок.
