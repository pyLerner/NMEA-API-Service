#!/usr/bin/env bash
# Сборка onefile standalone для NMEA-API-Service → Build-NaviTerminal.dist/naviapiserv.bin
# Запускать на Linux aarch64 с установленным gcc/clang и uv (или заранее: uv sync).
#
# Если bash пишет «Отказано в доступе» при ./scripts/... — у файла нет бита исполнения:
#   chmod +x scripts/build-naviapiserv-aarch64.sh
# или запускайте без +x:
#   bash scripts/build-naviapiserv-aarch64.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_NAME="${DIST_NAME:-Build-NaviTerminal.dist}"
# Переопределение каталога вывода, примеры:
#   OUT_DIR=/abs/path ./scripts/build-naviapiserv-aarch64.sh
#   OUT_DIR=/abs/path bash scripts/build-naviapiserv-aarch64.sh
OUT_DIR="${OUT_DIR:-$ROOT/$DIST_NAME}"
# После сборки удалить промежуточные каталоги Nuitka в OUT_DIR (имя *.build), например main.build:
#   REMOVE_BUILD_DIRS=1 ./scripts/build-naviapiserv-aarch64.sh
# REMOVE_BUILD_DIRS="${REMOVE_BUILD_DIRS:-0}"

# Проверка архитектуры (не блокирует кросс, но предупреждает)
ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  echo "Warning: uname -m=$ARCH — для бинарника под aarch64 надёжнее собирать на aarch64." >&2
fi

mkdir -p "$OUT_DIR"

cd "$ROOT"
# Зависимости приложения + Nuitka
uv sync

# Сборка: обход модулей из src/ как при запуске python из каталога src
# --nofollow-import-to: не тащить тестовые пакеты и unittest/pytest (Nuitka anti-bloat)
cd "$ROOT/src"
uv run python -m nuitka \
  --standalone \
  --onefile \
  --assume-yes-for-downloads \
  --output-dir="$OUT_DIR" \
  --output-filename=naviapiserv.bin \
  --include-package=uvicorn \
  --include-package=fastapi \
  --include-package=starlette \
  --include-package=pydantic \
  --include-package=aiosqlite \
  --include-package=serial \
  --include-package=serial_asyncio \
  --nofollow-import-to='*.tests' \
  --nofollow-import-to='*.test' \
  --nofollow-import-to=unittest \
  --nofollow-import-to=pytest \
  --nofollow-import-to=doctest \
  --remove-output \
  main.py

# if [[ "$REMOVE_BUILD_DIRS" == "1" || "$REMOVE_BUILD_DIRS" == "yes" || "$REMOVE_BUILD_DIRS" == "true" ]]; then
#   shopt -s nullglob
#   for d in "$OUT_DIR"/*.build; do
#     if [[ -d "$d" ]]; then
#       rm -rf "$d"
#       echo "Removed: $d"
#     fi
#   done
#   shopt -u nullglob
# fi

echo "OK: $OUT_DIR/naviapiserv.bin"
ls -lh "$OUT_DIR/naviapiserv.bin"
