# T-181 — STTProvider и Vosk-воркер с моделью в репозитории

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-STT` (распознавание речи [BRD]) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Офлайн-потоковое распознавание русской речи внутри backend по интерфейсу STTProvider (ТЗ 5.3): partial/final с таймкодами слов, словарь терминов, метрики.

## Разделы ТЗ (docs/TZ.md)
§5, §5.1, §5.3, §16.1, §16.4

## Контракты
- `events/compliance/stt_result.schema.json`
- `api/openapi.yaml: stt/*, /ws/audio/{session_id}`
- `db/schema.sql: stt_metrics`

## Зависимости
- Зависит от: [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md)
- Блокирует: [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md), [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-193](T-193-opcionalnye-stt-provajdery-browser-web-speech-sa.md), [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md)

## Что сделать
1. app/stt/base.py: STTProvider (start_stream, feed, события partial/final, health, capabilities); реестр провайдеров и выбор по настройкам.
2. app/stt/vosk_provider.py: KaldiRecognizer на канал, SetWords(True), пользовательская грамматика из data/stt/vocab_ru.txt (продукты, «страховка», «ИСЖ», «НСЖ», «ПДС», «вклад», «формальность»); пул процессов, модель грузится один раз при старте, флаг --no-stt.
3. Модель vosk-model-small-ru-0.22 в data/models/stt/ (лицензия Apache-2.0 в docs/LICENSES.md); install.sh --stt-model large скачивает vosk-model-ru-0.42 с проверкой sha256 (единственная необязательная внешняя загрузка).
4. /ws/audio/{session_id}: hello/ready, PCM16 16 кГц чанки 100 мс, 1–2 канала; partial ≤ 0,5 с, final с latency_ms; дубль final в /ws/stream (stt, compliance).
5. stt_metrics: partial/final latency, cpu_ms, WER по эталону для source=file; GET /api/stt/providers, POST /api/stt/test.
6. Dockerfile backend: vosk wheel, ресурсы +1 ядро/0,3 ГБ на сессию.

## Критерии приёмки
- [ ] На предзаписанном файле stt_v1 WER small-модели ≤ 25 %, partial latency p50 ≤ 500 мс на 4 ядрах.
- [ ] Старт backend с моделью ≤ 90 с (small).
- [ ] Контейнер не обращается в сеть при --offline (тест egress).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_stt_vosk.py
python scripts/stt_bench.py --dataset stt_v1
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
