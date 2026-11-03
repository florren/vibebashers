# Совместная интеграция проверенных пакетов ревизии

Пакет объединяет индивидуально подготовленные PR183–206, перечисленные точными
heads в machine proof. PR180 уже согласован и merged вmain0742386; оба локальных
main синхронизированы. Это release-интеграция зависимой цепочки; карточки сохраняют
свои отдельные PR и evidence. API1.5.31, DDL до0020 и событие team journal сохранены.

Состав: история/run scope, Telegram delivery и QR-readiness, durable API quotas,
поведение/план команд, кабинет/калькулятор/отчёт, prevention receipts, CSI/ВСП,
Trace/Journey read-only переходы, CX/Обзор, карта, новый сигнал и явный STT opt-in,
автоматическая runtime metadata version. T020 native seed/guards, API32 reason,
полная temporal history/recovery/90s не входят. Первоначальный94-cardgoal
этим пакетом завершённым не объявляется.

## Точное объединение

Jury/API31d09 содержит все heads пакета кромеQR18565b. Этот ранее согласованный
QR merge добавлен обычным merge106caf2; единственный textual conflict — metadata
version23/31, сохранён31. Объекты canonicalAPI проверены программным three-way
merge: все изменения185 и31 сохранены, TS вновь generated из canonical.

Новыйmain0742386 — squash точного ancestor199290f, trees побайтно равны.
Обычный merge этого squash порождал повторные конфликты уже включённогоP1.
После проверки equality и ancestor выполнен ancestry merge3e9e592 без source
изменений; новыйmain действительно являетсяancestor. Чужие изменения не выбирались
ours вслепую; при различииtrees такой reconciliation запрещён.

## Проверки и merge gate

Индивидуальные source-qualified evidence находятся в PR/карточках. ПолныеCI
для183/184/185/188/193/195/196/197/198/199/200/201/203 ранееGREEN; новые202/204/
205/206 проходят свои exactheads. Это не заменяет полныйCI общегоhead.
Локально на application head3e9e592 прошли make lint (561 frontend/80 files,
форматирование, mypy, drift197/197), обе production-сборки,105 адресных backend
и50 bot tests. Это не полный backend suite. Индивидуальный CI202 выявил cold-report
p95=411.76ms при пороге300ms; CI206 выявил e2e ошибки подготовки301CSI agents,
URL scope и согласованности fixture. Эти ошибки расследуются, не игнорируются. Полный
requiredCI integration обязателен до merge, как и techlead review API30/31 и
совместной публикации. Реальные внешние LLM/STT/Telegram/email не вызывались;
production deployment/DB migration не выполняются gitmerge.

Merge нужно выполнить обычным merge commit, сохранив историю включённых heads.
После этого individual PR можно retargetmain с сохранением provenance; не squash/
переписывать индивидуальныеветки. Откат — reviewed revert выбранного пакета и
совместимая версиясервера; миграции/receipts/ciphertext/историю не удалять.

[Точныеheads и hash proof](REVISION-2026-11-03-integration-proof.json).
