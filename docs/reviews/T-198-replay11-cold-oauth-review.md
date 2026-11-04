# T-198 — cold startup recorder после ограниченного запуска

Первый отдельно согласованный план `b84e7e22…` был выполнен один раз и остановился:
1 OAuth transport attempt,0balance/0inference, primary bank и operational ledger
не изменились (22known/2reconciled/1unknown). Backup проверен. Повтор этим старым
согласованием не разрешён; marker, staging и приватные журналы сохранены.

Причина подтверждена из собственного checkpoint через штатный serializer:
`normalize: timeout: oauth: ConnectTimeout` (2062ms), затем локальный
`classify: auth: bounded_oauth_limit`, затем quota после локального отключения
этого ephemeral key. Это не доказательство неверного ключа. Одноразовый cold
recorder вызывал OAuth внутри generation path с connect2s и не выполнял штатный
startup приложения. Корневой дефект подготовки исправляется только в recorder.

## Новый конкретный план для отдельного разрешения

[Полные synthetic inputs/source fingerprints](T-198-replay11-cold-oauth-plan.json).
Canonical JSON SHA256:
`4dbb058cd0d4689084f59dfe142af353212a16f58ecb7bd69ae36c6ed09403b4`.

- Одна модель `GigaChat-3-Pro`, существующий `gigachat1`.
- Не более6inference,1OAuth,1GET/models и6GET/balance:14HTTP,8служебных.
- Штатный **public** `GigaChatProvider.prepare([profile], timeout_s=12)` заранее
  греет оба TLS hosts. Guard допускает models только один раз до inference и
  проверяет наличие нужного model ID. После prepare немедленно останавливается
  auth background task; дополнительных OAuth/models или фонового HTTP нет.
- Startup и graph входят в прежний общий timeout120s; generation timeout,
  production provider и node logic не меняются. На inference1024output tokens,
  максимум6144output tokens всего,16000characters/48000input UTF8 bytes,
 65536bytes JSON payload. TLS включён, fallback отсутствует.
- `recording_profile` явно замораживает temperature0.0 только в copied tooling
  profile. Primary profile/config/ID, caps и цены не изменяются. Это убирает
  необходимость постоянного monkeypatch bootstrap в execution driver.
- По-прежнему используются текущие primary accounting DSN/APP_SECRET/profile ID,
  отдельная fresh synthetic bank DB и canonical read-only maintenance marker.
  В live нет connect-origin/reconciliation/reset. Unknown не превращается в0.
- Actual cost по тарифу заранее неизвестен: `cost_known=false`,
  `actual_cost_rub=null`. Generation payload previews не изменились относительно
  первого плана; dependent classify/decide hashes до live остаются неизвестными.

Actual offline prepare CLI выполнил только MockTransport:1OAuth+1models+3balance+
3inference; выходPASS. Никакого нового внешнего вызова после первого отказа не было.
Первый normalize payload11402bytes/input10743bytes,
SHA256 `c8cd6bfa1ba2101a4d91fb3d5473746b7bc681c9c4bf05b11400e23974a1a55c`.
Classify/decide fake previews15979/18489bytes; full JSON содержит их явные ограничения.

## Проверки

Cold regression воспроизводит прежний RED: fake cold OAuth требует connect>2s,
старый generation token call даёт ConnectTimeout. Исправленный public prepare
греет OAuth и API/models с12s budget, graph использует тот же cached token и
API connection; одна OAuth, одна models, background task остановлена.
Native two-DSN cases дополнительно воспроизводят полный прежний timeout→локальный
bounded_oauth_limit→quota без inference, затем проверяют успешный startup на
profile id2/codegigachat_pro/temp0.7 с frozen copy0.0 и unchanged исходным SQL config.
Cap2 и unknown usage по-прежнему блокируют следующие inference до HTTP.

Отдельно проверен риск Decimal: обычный DB-like LLMProfile содержит Decimal prices,
но фактический `record→run_profiles.capture→roles.select` преобразует их в float
до каждого provider call. Native cases с0 и4.50/6.25 подтверждают численную
эквивалентность Decimal(str(float)), working `cost(10,20)`, неизменные ID/caps.
Дополнительный production price fix не требуется и не добавлен.

Новый genuine scenario11 test использует только immutable fresh bank и
ReplayProvider с append_mock=False, три actual replay/ok nodes, отсутствие
error/fallback steps, actual sent clarification/wake1/escalationcx_lead и
changed-context real miss. До настоящей проверенной кассеты он честно пропускается.
Mock response не публикуется в data/cassettes.

Итог targeted gate: **33unit+7native PG=40passed48.21s**, skipped0.
Покрытие [нового producer](T-198-replay11-cold-oauth-coverage.json):177/193 AST
statement starts=91.71%; все5 selector lines исполнены. Ruff/format и strict mypy
затронутых app modules прошли. Предыдущий полный unit на исходной подготовке
был2296passed/19skipped; новый полный gate выполняется отдельно после композиции.

## Команда и откат

Тот же CLI с новым планом, новым private staging и отдельным новым согласованием:

```bash
ENV_FILE=/private/runtime.env LLM_PROVIDER=gigachat PYTHONPATH=backend:. \
  backend/.venv/bin/python scripts/replay11_record.py live \
  --bank-dsn-file /private/new-bank-connection.json \
  --output var/recordings/replay11-cold-live-new \
  --plan docs/reviews/T-198-replay11-cold-oauth-plan.json \
  --approved-plan-sha256 4dbb058cd0d4689084f59dfe142af353212a16f58ecb7bd69ae36c6ed09403b4 \
  --profile-id EXISTING_PRIMARY_GIGACHAT_PRO_PROFILE_ID
```

Source и plan проверяются до выбора credential; O_EXCL marker и exclusive output
не допускают повтор. В executor используется CI image с readonly source snapshot,
primary data/CA/maintenance volumes readonly и private0600envfile, без секретов
в argv/stdout. Перед запуском сохраняется полный private PG backup с TOC proof.
После — сверка primary bank hashes и native ledger attempts. Новый staging не
публикуется автоматически; genuine import разрешён только после strict replay,
schema/provenance/secret review. Кодовый откат возвращает прежнюю cold-start
ошибку recorder; primary runtime/config, ledger и исторические кассеты не меняются.
