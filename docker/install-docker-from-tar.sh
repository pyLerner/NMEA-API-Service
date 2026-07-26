#!/usr/bin/env bash
# Развёртывание из каталога, где лежат подкаталог navigator/ и архив navigator*.tar.gz
# — загрузка образа (docker load), остановка/удаление контейнера при обновлении, запуск compose.
# Опционально: копирование navigator → /opt/navigator.
set -euo pipefail

COMPOSE_REL_PATH="${COMPOSE_REL_PATH:-}"
DEFAULT_CONTAINER_NAME="${CONTAINER_NAME:-navigator}"
OPT_TARGET="/opt/navigator"
PROJECT_DIR_NAME="${PROJECT_DIR_NAME:-navigator}"

usage() {
  cat <<'EOF'
Usage: install-docker-from-tar.sh [options] [DEPLOY_DIR]

  DEPLOY_DIR — каталог с navigator/ и navigator*.tar.gz (по умолчанию: текущий).

Options:
  --copy-to-opt       Скопировать navigator в /opt/navigator (нужен root).
                      Не затираются: .env, .terminal-id, db/ (rsync --exclude).
                      После копирования: интерактивно terminal-id; при отсутствии
                      .env — предложить создать из .env.example (chmod 600).
  --no-up             Только docker load (и опционально --copy-to-opt), без запуска.
  --tar FILE          Явный путь к .tar.gz; иначе ищется navigator*.tar.gz в DEPLOY_DIR.
  -h, --help          Справка.

Переменные окружения:
  TAR_FILE            То же, что --tar.
  CONTAINER_NAME      Имя контейнера для остановки перед обновлением (по умолчанию: navigator).
  COMPOSE_REL_PATH    Путь к compose от корня bundle (по умолчанию: docker-compose.yml).
  PROJECT_DIR_NAME    Имя каталога проекта в bundle (по умолчанию: navigator).

Несколько файлов navigator*.tar.gz: берётся самый новый по дате модификации.
EOF
}

log() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "команда не найдена: $1"
}

pick_newest_tar() {
  local -n __arr=$1
  local newest="" mt=-1 t
  [[ ${#__arr[@]} -gt 0 ]] || return 1
  for f in "${__arr[@]}"; do
    if [[ ! -f "$f" ]]; then
      continue
    fi
    t=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
    if (( t > mt )); then
      mt=$t
      newest=$f
    fi
  done
  [[ -n "$newest" ]] || return 1
  printf '%s' "$newest"
}

resolve_tar_path() {
  local dir="$1"
  if [[ -n "${TAR_FILE:-}" ]]; then
    [[ -f "$TAR_FILE" ]] || die "файл не найден: $TAR_FILE"
    realpath -s "$TAR_FILE" 2>/dev/null || readlink -f "$TAR_FILE" 2>/dev/null || printf '%s' "$TAR_FILE"
    return
  fi
  local -a candidates=()
  shopt -s nullglob
  candidates=( "${dir}"/navigator*.tar.gz )
  shopt -u nullglob
  ((${#candidates[@]} == 0)) && die "в $dir нет файлов navigator*.tar.gz (задайте --tar или TAR_FILE=)"
  if ((${#candidates[@]} > 1)); then
    log "Найдено несколько архивов, выбран самый новый по mtime:"
    printf '  %s\n' "${candidates[@]}"
  fi
  pick_newest_tar candidates || die "не удалось выбрать архив"
}

stop_existing_container() {
  local name="$1"
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Fxq "$name"; then
    log "Останавливаю и удаляю контейнер «$name» (обновление образа)…"
    docker rm -f "$name" >/dev/null
  fi
}

compose_down_project() {
  local root="$1"
  local cf="${root}/${COMPOSE_REL_PATH}"
  [[ -f "$cf" ]] || return 0
  log "docker compose down в ${root}…"
  ( cd "$root" && docker compose -f "$COMPOSE_REL_PATH" down --remove-orphans 2>/dev/null ) || true
}

# Trim leading/trailing whitespace and CR/LF.
_trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  s="${s//$'\r'/}"
  printf '%s' "$s"
}

_file_has_content() {
  local f=$1
  [[ -f "$f" && -s "$f" ]] || return 1
  local t
  t=$(_trim "$(cat "$f")")
  [[ -n "$t" ]]
}

# Read a line from the controlling terminal (works under sudo).
_read_tty() {
  local prompt=$1
  local __var=$2
  local line=""
  if [[ -r /dev/tty ]]; then
    printf '%s' "$prompt" >/dev/tty
    IFS= read -r line </dev/tty || true
  else
    printf '%s' "$prompt" >&2
    IFS= read -r line || true
  fi
  printf -v "$__var" '%s' "$line"
}

ensure_terminal_id() {
  local path="${OPT_TARGET}/.terminal-id"
  local current="" input=""

  if _file_has_content "$path"; then
    current=$(_trim "$(cat "$path")")
    log "Найден ${path}."
    _read_tty "terminal-id [${current}]: " input
    input=$(_trim "$input")
    if [[ -z "$input" ]]; then
      input=$current
      log "Оставлен terminal-id по умолчанию."
    fi
  else
    log "Значение terminal-id не установлено — необходимо ввести."
    while true; do
      _read_tty "terminal-id: " input
      input=$(_trim "$input")
      if [[ -n "$input" ]]; then
        break
      fi
      warn "пустое значение недопустимо, повторите ввод"
    done
  fi

  printf '%s\n' "$input" >"$path"
  chmod 644 "$path" || true
  log "Записан ${path}"
}

ensure_env_file() {
  local path="${OPT_TARGET}/.env"
  local example="${OPT_TARGET}/.env.example"
  local ans=""

  if _file_has_content "$path"; then
    log "Найден ${path} (содержимое не выводится)."
    return 0
  fi

  log "${path} отсутствует или пуст."
  if [[ ! -f "$example" ]]; then
    warn "нет ${example} в bundle — создайте ${path} вручную (NAVAPI_API_TOKEN=…) перед compose up"
    return 0
  fi

  _read_tty "Создать ${path} из .env.example? [Y/n]: " ans
  ans=$(_trim "${ans:-Y}")
  case "$ans" in
    "" | y | Y | yes | YES)
      cp "$example" "$path"
      chmod 600 "$path"
      # Владелец как у каталога /opt/navigator (обычно root при --copy-to-opt).
      if [[ -d "${OPT_TARGET}" ]]; then
        chown --reference="${OPT_TARGET}" "$path" 2>/dev/null \
          || chown "$(stat -c '%u:%g' "${OPT_TARGET}" 2>/dev/null || echo root:root)" "$path" 2>/dev/null \
          || true
      fi
      log "Создан ${path} (режим 600). Задайте NAVAPI_API_TOKEN перед использованием API."
      ;;
    *)
      warn "создание ${path} пропущено — создайте файл вручную перед compose up"
      ;;
  esac
}

copy_project_to_opt() {
  local src="$1"
  [[ -d "$src" ]] || die "нет каталога: $src"
  need_cmd rsync
  log "Копирование ${src} → ${OPT_TARGET} …"
  mkdir -p "${OPT_TARGET}"

  # --delete зеркалит bundle, но не трогает локальные секреты, terminal-id и данные SQLite.
  rsync -a --delete \
    --exclude='.env' \
    --exclude='db/' \
    --exclude='db' \
    --exclude='.terminal-id' \
    "${src}/" "${OPT_TARGET}/"

  mkdir -p "${OPT_TARGET}/etc" "${OPT_TARGET}/db" "${OPT_TARGET}/log"

  ensure_terminal_id
  ensure_env_file

  if [[ -d "${OPT_TARGET}/db" ]]; then
    log "Каталог данных ${OPT_TARGET}/db сохранён/создан"
  fi
}

resolve_compose_rel_path() {
  local root="$1"
  if [[ -n "${COMPOSE_REL_PATH}" ]]; then
    return 0
  fi
  if [[ -f "${root}/docker-compose.yml" ]]; then
    COMPOSE_REL_PATH="docker-compose.yml"
    return 0
  fi
  if [[ -f "${root}/docker/docker-compose.yml" ]]; then
    warn "Используется устаревший путь docker/docker-compose.yml; ожидается ${root}/docker-compose.yml"
    COMPOSE_REL_PATH="docker/docker-compose.yml"
    return 0
  fi
  die "не найден compose в ${root} (ожидается docker-compose.yml)"
}

load_image_from_tar() {
  local tar_path="$1"
  local load_out loaded=""
  load_out=$(gunzip -c "$tar_path" | docker load 2>&1)
  printf '%s\n' "$load_out" >&2
  loaded=$(printf '%s\n' "$load_out" | sed -n 's/^Loaded image: //p' | tail -n 1)
  if [[ -z "$loaded" && -f "${2:-}/IMAGE_TAG" ]]; then
    loaded=$(tr -d ' \t\r\n' < "${2}/IMAGE_TAG")
    warn "Тег из docker load не распознан; используется IMAGE_TAG: ${loaded}"
  fi
  [[ -n "$loaded" ]] || die "не удалось определить тег образа после docker load"
  printf '%s' "$loaded"
}

patch_compose_for_offline() {
  local compose_file="$1"
  local image="$2"
  [[ -f "$compose_file" ]] || die "compose не найден: $compose_file"

  if grep -qE '^[[:space:]]*image:' "$compose_file"; then
    sed -i -E "s|^[[:space:]]*image:.*|    image: ${image}|" "$compose_file"
  else
    die "в ${compose_file} нет строки image:"
  fi

  if grep -qE '^[[:space:]]*pull_policy:' "$compose_file"; then
    sed -i -E 's/^[[:space:]]*pull_policy:.*/    pull_policy: never/' "$compose_file"
  else
    sed -i -E "/^[[:space:]]*image:/a\\    pull_policy: never" "$compose_file"
  fi

  log "Compose ${compose_file}: image=${image}, pull_policy=never"
}

remove_legacy_compose() {
  local root="$1"
  if [[ -f "${root}/docker-compose.yml" && -f "${root}/docker/docker-compose.yml" ]]; then
    log "Удаляю устаревший ${root}/docker/docker-compose.yml (используется docker-compose.yml в корне)"
    rm -f "${root}/docker/docker-compose.yml"
  fi
}

start_stack() {
  local project_root="$1"
  log "Запуск stack в ${project_root} …"
  ( cd "$project_root" && docker compose -f "$COMPOSE_REL_PATH" up -d --no-build --pull never )
}

main() {
  local deploy_dir=""
  local copy_to_opt=0
  local no_up=0
  local tar_explicit=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --copy-to-opt)
        copy_to_opt=1
        shift
        ;;
      --no-up)
        no_up=1
        shift
        ;;
      --tar)
        [[ -n "${2:-}" ]] || die "ожидается путь после --tar"
        tar_explicit=$2
        shift 2
        ;;
      -*)
        die "неизвестный параметр: $1"
        ;;
      *)
        [[ -z "$deploy_dir" ]] || die "указано несколько каталогов"
        deploy_dir=$1
        shift
        ;;
    esac
  done

  need_cmd docker
  deploy_dir="${deploy_dir:-.}"
  deploy_dir=$(cd "$deploy_dir" && pwd)

  if [[ -n "$tar_explicit" ]]; then
    TAR_FILE=$tar_explicit
  fi

  local src_project="${deploy_dir}/${PROJECT_DIR_NAME}"
  [[ -d "$src_project" ]] || die "ожидается каталог: ${src_project}"

  local tar_path
  tar_path=$(resolve_tar_path "$deploy_dir")
  [[ -f "$tar_path" ]] || die "архив образа: $tar_path"

  local project_root="$src_project"
  if (( copy_to_opt )); then
    if [[ "${EUID}" -ne 0 ]]; then
      die "для --copy-to-opt запустите от root: sudo $0 ..."
    fi
    copy_project_to_opt "$src_project"
    project_root="${OPT_TARGET}"
  fi

  resolve_compose_rel_path "${project_root}"
  remove_legacy_compose "${project_root}"

  local compose_file="${project_root}/${COMPOSE_REL_PATH}"
  [[ -f "$compose_file" ]] || die "не найден compose: $compose_file (COMPOSE_REL_PATH=${COMPOSE_REL_PATH})"

  compose_down_project "$project_root"
  stop_existing_container "$DEFAULT_CONTAINER_NAME"

  log "Загрузка образа из ${tar_path} …"
  local loaded_image
  loaded_image=$(load_image_from_tar "$tar_path" "$project_root")

  patch_compose_for_offline "$compose_file" "$loaded_image"

  if (( no_up )); then
    log "Готово (--no-up: контейнер не запускался)."
    exit 0
  fi

  start_stack "$project_root"
  log "Готово."
}

main "$@"
