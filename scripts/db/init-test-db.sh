#!/bin/sh
# Создаёт тестовую БД рядом с основной при первом старте контейнера postgres.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE cx_pulse_test OWNER $POSTGRES_USER;"
