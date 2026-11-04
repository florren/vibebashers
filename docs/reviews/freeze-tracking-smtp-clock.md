# Freeze: локальная SMTP-квитанция и её wall clock

Основа: main7fe3f85. Проверка не использует внешнюю почту, реальные контакты,
production или настройки рабочего стенда. Mailpit image/binary на машине не найден;
настоящий SMTP protocol проверен через локальный stdlib sink, который не умеет relay.
Принятый MIME отдельно читается через localhost HTTP. Это не проверка самого Mailpit.

## Обнаружение и граница

`send_tracking_receipt` фиксировал успешную отправку через `now()`, то есть время
начала переданной PostgreSQL-транзакции. Воспроизводимая проверка: mail transaction
начата раньше вопроса в другом соединении; native SMTP успешно принял квитанцию,
но `sent_at=11:01:16.254197` раньше `received_at=11:01:16.260662`.
Регрессия на исходном коде RED; обычный public claim через отдельный новый mail
connection на исходном коде GREEN. Это различие сохраняется: проверка не утверждает,
что сегодняшний обычный `/api/public/claim` создавал инверсии.

Минимальная правка — `clock_timestamp()` только для wall timestamp успешной SMTP
квитанции. Параметры SMTP, получатель, согласие, тексты, capability URL, sim time,
денежные формулы и HITL не меняются; история не переписывается. Rollback — вернуть
эту строку к `now()`; DDL и миграций нет.

## Проверки

- RED: новый native SMTP тест на older transaction падает на `sent_at>=question`;
  actual public API claim/SMTP/tracking test проходит: 1 failed/1 passed.
- GREEN: 30 SMTP/public tracking/channel chronology/privacy cases прошли за137.11s.
- Дополнительный native recipient-rejection case проверяет failed и отсутствие
  `sent_at/sent_sim`; финальный повтор всех трёх native SMTP cases прошёл за26.92s.
- Ruff check/format для обоих затронутых Python files прошли.

SMTP приём подтверждён по настоящим protocol ACK, MIME recipient/from/subject/body
и локальному HTTP-чтению. Capability URL присутствует только в письме, безопасная
notification его не хранит. Два tracking GET и повтор с использованной captcha
не отправляют второе письмо. Это не обещание exactly-once внешней SMTP-доставки:
transactional outbox/recovery для email здесь не добавлены.

Общий `notify_client(channel='email')` по-прежнему записывает виртуальное
уведомление, без SMTP. Реальный локальный SMTP реализован только для tracking
receipt публичного обращения; статусы этих двух контуров не следует смешивать.
