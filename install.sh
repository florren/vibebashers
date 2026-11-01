#!/usr/bin/env bash
# CX Pulse Control — установка одной командой (ТЗ 16.2, T-003).
# ./install.sh [--profile lite|demo|stress] [--offline] [--record-cassettes] [--reset] [--seed N] [--no-mailpit] [--with-tgbot] [--help]
set -euo pipefail
cd "$(dirname "$0")"

PROFILE=""; OFFLINE=0
NO_STT=0; RECORD_CASSETTES=0; RESET=0; SEED=""; MAILPIT=0; TGBOT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    --no-stt) NO_STT=1; shift ;;
    --record-cassettes) RECORD_CASSETTES=1; shift ;;
    --reset) RESET=1; shift ;;
    --seed) SEED="$2"; shift 2 ;;
    --no-mailpit) MAILPIT=0; shift ;;
    --with-mailpit) MAILPIT=1; shift ;;
    --with-tgbot) TGBOT=1; shift ;;
    --help|-h) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Неизвестный флаг: $1 (см. --help)"; exit 2 ;;
  esac
done

say() { printf '\033[1;32m▸\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "Нужен Python 3 для подготовки модели и запуска туннеля"
command -v docker >/dev/null || die "Docker не найден. Установите Docker Engine ≥ 24 и docker compose v2: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "docker compose v2 не найден (нужна команда «docker compose», не «docker-compose»)"
docker info >/dev/null 2>&1 || die "Docker не запущен или нет прав (добавьте пользователя в группу docker: sudo usermod -aG docker \$USER)"
for p in 5432 8000 9999; do
  if (command -v ss >/dev/null && ss -ltn 2>/dev/null | grep -q ":$p ") ; then
    docker compose ps --status running 2>/dev/null | grep -q cx-pulse || die "Порт $p занят другим процессом"
  fi
done

if [ ! -f .env ]; then
  cp .env.example .env
  secret=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))' 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -d '/+=')
  sed -i.bak "s|^APP_SECRET=.*|APP_SECRET=$secret|" .env && rm -f .env.bak
  say ".env создан из .env.example (APP_SECRET сгенерирован). Ключи GigaChat впишите в .env и перезапустите."
fi
existing_profile=$(python3 -c 'import pathlib,re,sys; s=pathlib.Path(sys.argv[1]).read_text(); m=re.search(r"^PROFILE\s*=\s*([^\s#]+)",s,re.M); print(m[1].strip(chr(34)+chr(39)) if m else "lite")' .env)
PROFILE=${PROFILE:-$existing_profile}
case "$PROFILE" in lite|demo|stress) ;; *) die "Неизвестный профиль: $PROFILE" ;; esac
if [ "$PROFILE" != "$existing_profile" ]; then
  sed -i.bak "s|^PROFILE=.*|PROFILE=$PROFILE|" .env && rm -f .env.bak
fi
[ -n "$SEED" ] && sed -i.bak "s|^SIM_SEED=.*|SIM_SEED=$SEED|" .env && rm -f .env.bak
if [ "$OFFLINE" = 1 ]; then
  sed -i.bak "s|^LLM_PROVIDER=.*|LLM_PROVIDER=mock|; s|^LLM_CHAIN=.*|LLM_CHAIN=replay,mock|; s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=|" .env && rm -f .env.bak
  say "режим --offline: LLM replay → mock, бот выключен"
fi
if [ "$RECORD_CASSETTES" = 1 ]; then
  sed -i.bak "s|^LLM_RECORD=.*|LLM_RECORD=1|" .env && rm -f .env.bak
  say "режим --record-cassettes: LLM_RECORD=1, ответы live-модели пишутся в data/cassettes"
fi

PROFILES=()
[ "$MAILPIT" = 1 ] && PROFILES+=(--profile tools)
if [ "$RESET" = 1 ]; then
  say "сброс: удаляю тома БД"
  docker compose "${PROFILES[@]}" down -v --remove-orphans
fi

if [ "$NO_STT" != 1 ]; then
  if [ "$OFFLINE" != 1 ]; then
    say "подготовка локальной диктовки Vosk"
    python3 scripts/stt_model.py || die "модель Vosk не подготовлена; проверьте сеть или явно используйте --no-stt"
  elif [ ! -d data/models/stt/vosk-model-small-ru-0.22/am ]; then
    say "--offline: модели Vosk нет; диктовка недоступна, заранее выполните make stt-model"
  fi
fi
say "сборка и запуск (профиль данных: $PROFILE)"
docker compose "${PROFILES[@]}" up -d --build
say "ожидание PostgreSQL и миграций"
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" = 60 ] && die "backend не поднялся за 120 с: docker compose logs backend"
done
say "сид данных ($PROFILE)"
if docker compose exec -T backend python /scripts/seed/run.py --if-needed --profile "$PROFILE" ${SEED:+--seed "$SEED"}; then
  say "seed-этап завершён; при существующих данных выполнена только проверка"
else
  seed_status=$?
  die "seed-этап завершился с кодом $seed_status (2 — coverage, 3 — baseline/pg_dump, 4 — незавершённый seed). Установка остановлена; автоматического сброса данных нет."
fi

HEALTH=$(curl -fs http://localhost:8000/api/health)
say "health: $HEALTH"
URL="http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):8000"
say "Интерфейс: $URL  · API: $URL/api/health  · документация: $URL/docs  · WebSocket: ws://…/ws/stream"
say "мастер настройки (UI) появится в E1 (T-010): $URL/setup"
if command -v python3 >/dev/null && python3 -c 'import qrcode' 2>/dev/null; then
  python3 -c "import qrcode,sys;q=qrcode.QRCode(border=1);q.add_data('$URL');q.print_ascii(invert=True)"
fi

say "ожидание отдельного пользовательского чата :9999"
for i in $(seq 1 60); do
  if curl -fs http://127.0.0.1:9999/api/personal/health >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" = 60 ] && die "публичный чат не поднялся: docker compose logs personal"
done
say "Анонимный чат: http://localhost:9999 (без операторского интерфейса)"
if [ "$OFFLINE" != 1 ]; then
  python3 scripts/tuna_tunnel.py start --env-file .env || die "Tuna не подтвердил готовность; локальные интерфейсы работают"
else
  python3 scripts/tuna_tunnel.py stop --env-file .env
  say "--offline: внешний туннель не запускается"
fi
