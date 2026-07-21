#!/usr/bin/env bash

set -euo pipefail

NAVAPI_CONFIG="/etc/navigator/navapiserv-config.toml"

log() {
    printf '%s [INFO] %s\n' "$(date -Iseconds)" "$*"
}

warn() {
    printf '%s [WARNING] %s\n' "$(date -Iseconds)" "$*" >&2
}

err() {
    printf '%s [ERROR] %s\n' "$(date -Iseconds)" "$*" >&2
}

cleanup() {
    log "Trapped SIGTERM. Stopping all processes..."
    kill $(jobs -p) 2>/dev/null || true
    wait || true
    log "All processes stopped. Exiting."
    exit 0
}
trap cleanup SIGTERM SIGINT

if [[ ! -x /bin/naviapiserv.bin ]]; then
    err "Missing executable: /bin/naviapiserv.bin"
    exit 1
fi

if [[ ! -f "$NAVAPI_CONFIG" ]]; then
    err "Missing NavAPI config: $NAVAPI_CONFIG"
    exit 1
fi

log "Starting NavAPI app..."
/bin/naviapiserv.bin --config "$NAVAPI_CONFIG" &

shopt -s nullglob
configs=(/etc/navigator/*.toml)
shopt -u nullglob

ndtp_configs=()
for conf in "${configs[@]}"; do
    # NDTP_Client: только TOML с секцией [NDTP] (не navapiserv / VehicleProfiles и т.п.)
    if grep -qE '^\[NDTP\]' "$conf" 2>/dev/null; then
        ndtp_configs+=("$conf")
    fi
done

if ((${#ndtp_configs[@]} == 0)); then
    warn "No NDTP client config files found in /etc/navigator/."
    warn "NDTP_Client will NOT be started."
else
    log "Found ${#ndtp_configs[@]} NDTP config file(s). Validating..."

    for conf in "${ndtp_configs[@]}"; do
        log "Processing config: $conf"

        if [[ ! -x /bin/NDTP_Client ]]; then
            err "Missing executable: /bin/NDTP_Client"
            continue
        fi

        ndtp_section="$(awk '/^\[NDTP\]/{flag=1;next}/^\[/{flag=0}flag' "$conf")"
        host="$(echo "$ndtp_section" | grep -i '^[[:space:]]*Host[[:space:]]*=' | head -n 1 | awk -F'=' '{print $2}' | tr -d ' "' || true)"
        port="$(echo "$ndtp_section" | grep -i '^[[:space:]]*Port[[:space:]]*=' | head -n 1 | awk -F'=' '{print $2}' | tr -d ' "' || true)"

        if [[ -z "$host" || -z "$port" ]]; then
            err "Could not parse Host or Port inside [NDTP] section of $conf. Skipping."
            continue
        fi

        log "Starting NDTP_Client for target ${host}:${port}..."
        /bin/NDTP_Client --config "$conf" &
    done
fi

log "Startup completed. Monitoring processes."
wait
