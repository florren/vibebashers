# Кассеты replay (T-194)

`<provider>.jsonl` — по одной записи на строку: `request_hash` (sha256 provider+model+нормализованные сообщения+схема),
`provider`, `model`, `response`, `chunks`, `usage`, `recorded_at`, `messages`. Запись: `LLM_RECORD=true` в `.env`
(успешные ответы live-провайдеров). Воспроизведение: провайдер `replay` в `LLM_CHAIN`. Кассеты не должны содержать
секретов и ПДн — проверяет `backend/tests/unit/test_llm_chain.py::test_cassettes_have_no_secrets`.
