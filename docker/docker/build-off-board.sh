#!/usr/bin/env bash
set -euo pipefail

# Cross-build linux/arm64 image on dev machine (x86) for RK3588 deployment.
# Prerequisites (one-time):
#   docker buildx create --name navigator-builder --use 2>/dev/null || docker buildx use navigator-builder
#   docker run --privileged --rm tonistiigi/binfmt --install all

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-navigator:2-kalman-ecef}"
EXPORT_TAR_DEFAULT="${DOCKER_DIR}/navigator-2-kalman-ecef-$(date +%Y%m%d).tar.gz"
BUNDLE_DIR_NAME="${BUNDLE_DIR_NAME:-NavigatorDockerApp-KF-ECEF}"
BUNDLE_TAR_DEFAULT="${DOCKER_DIR}/${BUNDLE_DIR_NAME}-$(date +%Y%m%d).tar.gz"
BUILDER_NAME="${BUILDER_NAME:-navigator-builder}"
PROJECT_DIR_NAME="${PROJECT_DIR_NAME:-navigator}"

if [[ -n "${EXPORT_TAR:-}" ]]; then
  if [[ "${EXPORT_TAR}" = /* ]]; then
    EXPORT_TAR_PATH="${EXPORT_TAR}"
  else
    EXPORT_TAR_PATH="${DOCKER_DIR}/${EXPORT_TAR}"
  fi
else
  EXPORT_TAR_PATH="${EXPORT_TAR_DEFAULT}"
fi

if [[ -n "${BUNDLE_TAR:-}" ]]; then
  if [[ "${BUNDLE_TAR}" = /* ]]; then
    BUNDLE_TAR_PATH="${BUNDLE_TAR}"
  else
    BUNDLE_TAR_PATH="${DOCKER_DIR}/${BUNDLE_TAR}"
  fi
else
  BUNDLE_TAR_PATH="${BUNDLE_TAR_DEFAULT}"
fi

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "команда не найдена: $1"
}

ensure_buildx() {
  need_cmd docker
  if ! docker buildx version >/dev/null 2>&1; then
    die "docker buildx не найден; обновите Docker Engine"
  fi
  if ! docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1; then
    log "Создаю buildx builder «${BUILDER_NAME}»…"
    docker buildx create --name "${BUILDER_NAME}" --use
  else
    docker buildx use "${BUILDER_NAME}"
  fi
  if ! docker buildx inspect --bootstrap >/dev/null 2>&1; then
    die "не удалось инициализировать buildx builder"
  fi
}

build_deploy_bundle() {
  local bundle_root="${DOCKER_DIR}/${BUNDLE_DIR_NAME}"
  local bundle_project="${bundle_root}/${PROJECT_DIR_NAME}"
  local image_basename
  image_basename="$(basename "${EXPORT_TAR_PATH}")"

  [[ -f "${EXPORT_TAR_PATH}" ]] || die "архив образа не найден: ${EXPORT_TAR_PATH}"
  [[ -f "${DOCKER_DIR}/install-docker-from-tar.sh" ]] || die "нет install-docker-from-tar.sh в ${DOCKER_DIR}"
  [[ -f "${SCRIPT_DIR}/docker-compose.yml" ]] || die "нет production compose: ${SCRIPT_DIR}/docker-compose.yml"
  [[ -f "${DOCKER_DIR}/NavAPIServer/bin/naviapiserv.bin" ]] || die "нет NavAPIServer/bin/naviapiserv.bin"
  [[ -f "${DOCKER_DIR}/NDTPClient/bin/NDTP_Client" ]] || die "нет NDTPClient/bin/NDTP_Client"

  need_cmd rsync
  rm -rf "${bundle_root}"
  mkdir -p "${bundle_project}"

  log "Сборка deploy bundle в ${BUNDLE_TAR_PATH}…"
  rsync -a \
    --exclude 'docker/' \
    --exclude 'NavAPIServer/' \
    --exclude 'NDTPClient/' \
    --exclude 'install-docker-from-tar.sh' \
    --exclude 'docker-compose.dev.yml' \
    --exclude "${BUNDLE_DIR_NAME}/" \
    --exclude 'navigator-*.tar.gz' \
    --exclude 'NavigatorDockerApp-*.tar.gz' \
    "${DOCKER_DIR}/" "${bundle_project}/"
  cp "${SCRIPT_DIR}/docker-compose.yml" "${bundle_project}/docker-compose.yml"
  printf '%s\n' "${IMAGE_TAG}" > "${bundle_project}/IMAGE_TAG"
  cp "${EXPORT_TAR_PATH}" "${bundle_root}/${image_basename}"
  cp "${DOCKER_DIR}/install-docker-from-tar.sh" "${bundle_root}/"
  chmod +x "${bundle_root}/install-docker-from-tar.sh"

  tar -czf "${BUNDLE_TAR_PATH}" -C "${DOCKER_DIR}" "${BUNDLE_DIR_NAME}"
  rm -rf "${bundle_root}"

  log "Deploy bundle: ${BUNDLE_TAR_PATH}"
}

cd "${DOCKER_DIR}"
ensure_buildx

log "Сборка ${IMAGE_TAG} (linux/arm64)…"
docker buildx build \
  --platform linux/arm64 \
  --no-cache \
  -f docker/Dockerfile \
  -t "${IMAGE_TAG}" \
  --load \
  .

log "Экспорт образа в ${EXPORT_TAR_PATH}…"
mkdir -p "${DOCKER_DIR}"
docker save "${IMAGE_TAG}" | gzip > "${EXPORT_TAR_PATH}"

log "Готово: ${EXPORT_TAR_PATH}"
build_deploy_bundle
