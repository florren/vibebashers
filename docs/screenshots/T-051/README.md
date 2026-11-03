# T-051 — UI профилей и привязки ключей

Четыре production UI снимка ru/en × light/dark из `frontend/e2e/profile-keys.spec.ts`. API transport полностью синтетический/локальный, модели и ключи — fixtures; это **не** доказательство живых LLM или реальных credential. Значение writeOnly password генерируется во время теста, не фиксируется в исходниках/снимках и очищено до screenshot.

- [Светлая, русский](profile-keys-light-ru.png)
- [Тёмная, русский](profile-keys-dark-ru.png)
- [Светлая, английский](profile-keys-light-en.png)
- [Тёмная, английский](profile-keys-dark-en.png)

Видны новый bound key, неизвестный GigaChat default endpoint с честной подсказкой, inactive/missing binding без auto-clear, остатки/лимиты из public API-проекции, пустой password input и обработанный DELETE409. Provider network calls не выполнялись; page errors/external requests0. Backend P1/контрактные gates описаны отдельно в `docs/reviews/T-051-runtime-profiles.md`.
