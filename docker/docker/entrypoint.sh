#!/bin/env bash

set -e

# Функция корректного завершения всех процессов
cleanup() {
    echo "$(date -Iseconds) [INFO] Trapped SIGTERM. Stopping all processes..."
    kill $(jobs -p) 2>/dev/null || true
    wait
    echo "$(date -Iseconds) [INFO] All processes stopped. Exiting."
    exit 0
}
trap cleanup SIGTERM SIGINT

# ==========================================
# 1. ЗАПУСК FASTAPI (Всегда работает)
# ==========================================
echo "$(date -Iseconds) [INFO] Starting NavAPI app..."
/app/NavAPIServer/bin/naviapiserv.bin \
    --config /data/NavAPIServer/etc/navapiserv-config.toml &

# ==========================================
# 2. ПРОВЕРКИ И ЗАПУСК GO ПРИЛОЖЕНИЙ
# ==========================================

shopt -s nullglob
configs=(/data/NDTPClient/etc/*.toml)
shopt -u nullglob

if [ ${#configs[@]} -eq 0 ]; then
    echo "$(date -Iseconds) [WARNING] No .toml config files found in /app/NDTPClient/etc/."
    echo "$(date -Iseconds) [WARNING] Go NDTP_Client will NOT be started."
else
    echo "$(date -Iseconds) [INFO] Found ${#configs[@]} config file(s). Validating..."
    
    for conf in "${configs[@]}"; do
        echo "----------------------------------------"
        echo "$(date -Iseconds) [INFO] Processing config: $conf"
        
        # 🎯 Вырезаем ТОЛЬКО секцию [NDTP] и парсим Host / Port внутри неё
        NDTP_SECTION=$(awk '/^\[NDTP\]/{flag=1;next}/^\[/{flag=0}flag' "$conf")
        
        HOST=$(echo "$NDTP_SECTION" | grep -i '^[[:space:]]*Host[[:space:]]*=' | head -n 1 | awk -F'=' '{print $2}' | tr -d ' "')
        PORT=$(echo "$NDTP_SECTION" | grep -i '^[[:space:]]*Port[[:space:]]*=' | head -n 1 | awk -F'=' '{print $2}' | tr -d ' "')
        
        # Если параметры не найдены в этой секции
        if [ -z "$HOST" ] || [ -z "$PORT" ]; then
            echo "$(date -Iseconds) [ERROR] Could not parse Host or Port inside [NDTP] section of $conf. Skipping."
            continue
        fi
        
        echo "$(date -Iseconds) [INFO] Extracted NDTP target $HOST:$PORT. Checking connection..."
        
        # Проверяем доступность TCP порта (таймаут 3 секунды)
        #if timeout 3 bash -c "nc -z $HOST $PORT" >/dev/null 2>&1; then
        #    echo "$(date -Iseconds) [INFO] Connection to $HOST:$PORT is OK. Starting NDTP_Client..."
        #    /app/NDTPClient/bin/NDTP_Client --config "$conf" &
        #else
        #    echo "$(date -Iseconds) [ERROR] Cannot reach server at $HOST:$PORT. Skipping this config."
        #fi

        echo "$(date -Iseconds) [INFO] Connection to $HOST:$PORT is OK. Starting NDTP_Client..."
        /app/NDTPClient/bin/NDTP_Client --config "$conf" &
    done
fi

echo "----------------------------------------"
echo "$(date -Iseconds) [INFO] All startup checks completed. Monitoring processes."

# ==========================================
# 3. ОЖИДАНИЕ
# ==========================================
wait

