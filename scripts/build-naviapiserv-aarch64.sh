#!/usr/bin/env bash
# Сборка onefile standalone для NMEA-API-Service → Buid-NaviTerninal.dist/naviapiserv.bin
# Целевая платформа: Rockchip RK3588, Ubuntu 20.04, aarch64.
#
# Собирать на native aarch64 с Ubuntu 20.04 (или совместимым glibc), иначе бинарник
# может не запуститься на целевой плате. Кросс-сборка с x86_64 этим скриптом не поддерживается.
#
# Требования на машине сборки: bash, gcc/clang, uv, Python 3.13 (uv подтянет из .python-version).
#
# Запуск:
#   bash scripts/build-naviapiserv-aarch64.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_NAME="${DIST_NAME:-Buid-NaviTerninal.dist}"
OUT_DIR="${OUT_DIR:-$ROOT/$DIST_NAME}"
OUTPUT_BIN="$OUT_DIR/naviapiserv.bin"

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  echo "Error: uname -m=$ARCH — для RK3588 нужна native-сборка на aarch64." >&2
  echo "       Запустите скрипт на Ubuntu 20.04 aarch64 (или ALLOW_CROSS_BUILD=1 для экспериментов)." >&2
  if [[ "${ALLOW_CROSS_BUILD:-0}" != "1" ]]; then
    exit 1
  fi
  echo "Warning: ALLOW_CROSS_BUILD=1 — бинарник может не работать на RK3588." >&2
fi

mkdir -p "$OUT_DIR"

cd "$ROOT"
# Только runtime-зависимости + группа build (Nuitka). Без pytest и dev-группы.
uv sync --no-dev --group build

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
  --nofollow-import-to=tests \
  --nofollow-import-to=unittest \
  --nofollow-import-to=pytest \
  --nofollow-import-to=doctest \
  --remove-output \
  main.py

if [[ ! -f "$OUTPUT_BIN" ]]; then
  echo "Error: expected binary not found: $OUTPUT_BIN" >&2
  exit 1
fi

echo "OK: $OUTPUT_BIN"
ls -lh "$OUTPUT_BIN"
file "$OUTPUT_BIN"
