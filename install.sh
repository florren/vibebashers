#!/usr/bin/env bash
# CX Pulse Control — установка одной командой (ТЗ 16.2, T-003).
# ./install.sh [--profile lite|demo|stress] [--offline] [--reset] [--seed N] [--no-mailpit] [--with-tgbot] [--help]
set -euo pipefail
cd "$(dirname "$0")"

PROFILE=lite; OFFLINE=0; RESET=0; SEED=""; MAILPIT=0; TGBOT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
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

command -v docker >/dev/null || die "Docker не найден. Установите Docker Engine ≥ 24 и docker compose v2: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "docker compose v2 не найден (нужна команда «docker compose», не «docker-compose»)"
docker info >/dev/null 2>&1 || die "Docker не запущен или нет прав (добавьте пользователя в группу docker: sudo usermod -aG docker \$USER)"
for p in 5432 8000; do
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
sed -i.bak "s|^PROFILE=.*|PROFILE=$PROFILE|" .env && rm -f .env.bak
[ -n "$SEED" ] && sed -i.bak "s|^SIM_SEED=.*|SIM_SEED=$SEED|" .env && rm -f .env.bak
if [ "$OFFLINE" = 1 ]; then
  sed -i.bak "s|^LLM_PROVIDER=.*|LLM_PROVIDER=mock|; s|^LLM_CHAIN=.*|LLM_CHAIN=replay,mock|; s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=|" .env && rm -f .env.bak
  say "режим --offline: LLM replay → mock, бот выключен"
fi

PROFILES=()
[ "$MAILPIT" = 1 ] && PROFILES+=(--profile tools)
if [ "$RESET" = 1 ]; then
  say "сброс: удаляю тома БД"
  docker compose "${PROFILES[@]}" down -v --remove-orphans
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
docker compose exec -T backend python /scripts/seed/run.py --profile "$PROFILE" ${SEED:+--seed "$SEED"} || say "сид ещё не реализован (E2) — пропуск"

HEALTH=$(curl -fs http://localhost:8000/api/health)
say "health: $HEALTH"
URL="http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):8000"
say "Интерфейс: $URL  · API: $URL/api/health  · документация: $URL/docs  · WebSocket: ws://…/ws/stream"
say "мастер настройки (UI) появится в E1 (T-010): $URL/setup"
if command -v python3 >/dev/null && python3 -c 'import qrcode' 2>/dev/null; then
  python3 -c "import qrcode,sys;q=qrcode.QRCode(border=1);q.add_data('$URL');q.print_ascii(invert=True)"
fi
