# Freeze: offline installer и reports_missing

На main1c022fe выполнен настоящий `./install.sh --profile lite --offline --no-stt --no-mailpit`.
Собственный checkout/project `cx-freeze-install-20261103`, новый PG16/volumes,
backend/personal только127.0.0.1:8000/9999; стандартный Dockerfile, отдельный image.
Compose isolation меняет project/image/публикацию портов; body установщика настоящий.
Первый install exit0: head0020, lite seed3.9s, coverage480/480, baseline1493715bytes,
healthok, Telegram disabled и tunnel остановлен. Production/чужой .env не использованы.
Это не fresh Ubuntu VM и не airgap proof; наличие offline flag не доказывает отсутствие egress.

## Найденный дефект и исправление

Повтор при работающих собственных контейнерах RED: «Порт8000 занят другим процессом».
Причина — substring `cx-pulse` в выводе compose ps. Она отвергает другое имя собственного
project и может принять посторонний порт, если в project работает любой cx-pulse сервис.
Теперь для каждого occupied default port требуются свой running service и его точный
published port. Ошибка compose, остановленный/чужой service, другой порт запрещают запуск;
имя project и IPv4/IPv6 адресу не мешают. Свободные порты проходят прежним путём.
Не менялись bind addresses продукта, flags reset, seed/миграции, деньги/HITL/аутентификация.
Регрессия3failed/6passed→9/9; вместе с существующими seed/record tests18passed,
Ruff/format/bash-n green. Полный backend unit:2171passed/19skipped58.89s.
Общий venv имел editable ссылку на старый checkout:5subprocess ImportErrors
устранены явным PYTHONPATH текущего backend; application code не правился. Rollback — revert только install.sh/test, volumes не удалять.

## Границы идемпотентности

Первый успешный повтор пересоздал backend после сборки и запустил существующий
`main._abs_backfill`: accounts1722→1723,ledger0→17891,audit5366→23257.
Seed сообщил `seed_existing_preserved`; новые проводки — штатная startup-инициализация,
не повторная генерация baseline. Полная неизменность этого прохода НЕ утверждается.
Следующий actual install exit0: все114table count+row hashes совпали. Проверены
balance≡Σledger (mismatches0),refund/reversal0,head0020. Существующая financial policy
не изменялась. Свои3контейнера остановлены, данные и volumes сохранены.

## T092: фактический пропущенный отчёт в UI

Через actual API/UI на том же main:12команд,16missing у5команд. Во всех ru/en×light/dark
точные reports_due/reports_missing совпали с API и получили text-danger; остальные
строки без ошибочной подсветки. Browser writes/externals/pageerrors0. Четыре PNG
в screenshots/T-092-reports-missing. Карточка сохраняет общий незавершённый DoD;
эта проверка закрывает только конкретный reports_missing acceptance.

[Machine proof](FREEZE-2026-11-03-offline-install-proof.json). Полный required CI
нового patch обязателен перед merge; proof не подменяет CI и внешние критерии.
