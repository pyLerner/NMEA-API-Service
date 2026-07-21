# API-PROTOCOL-v2

Протокол HTTP API сервиса `NMEA-API-Service`.

## 1. Общие положения

- Базовый URL формируется из параметров `[API].Host` и `[API].HTTP_Port`.
- Запросы с телом: заголовок `Content-Type: application/json`.
- Ответы: JSON в кодировке UTF-8.
- Ключи JSON в успешных ответах данных: **kebab-case** (например `record-id`, `lat-hemisphere`, `satellites-count`).
- **Авторизация:** пути `/api/ping` и `/api/navigator/v1/*`, `/api/navigator/v2/*` **не** требуют `Authorization`. Legacy (`/LastCoords`, …) требуют Bearer.

Набор эндпоинтов:

- `GET /api/ping`
- `GET /api/navigator/v1/last-coords`
- `GET /api/navigator/v1/all-coords`
- `DELETE /api/navigator/v1/delete-record/{record_id}`
- `GET /api/navigator/v2/last-coords` (SSE)
- `GET /api/navigator/v2/all-coords`

**Не входят в контракт:** служебные URL FastAPI (`/docs`, `/openapi.json`, `/redoc` и т.п.) — на них действует Bearer, как на legacy.

## 2. Legacy v1 (обратная совместимость)

Пути с обязательной Bearer-аутентификацией:

- `GET /LastCoords`
- `GET /AllCoords`
- `DELETE /DeleteRecord/{record_id}`

Формат JSON legacy: ключи как в [API-PROTOCOL-v1.md](API-PROTOCOL-v1.md) (`record_id`, `lat_hemisphere`, …). Поле `source` — в **том же составном формате**, что и в navigator API (см. §3).

## 3. Формат данных записи

| Поле | Тип | Описание |
|------|-----|----------|
| `record-id` | `integer` | Идентификатор записи; `0` если ещё не в БД. |
| `time` | `string \| null` | ISO8601 UTC timestamp. |
| `is-valid` | `"A" \| "V" \| null` | Валидность фикса. |
| `latitude` | `number` | Широта, **7** decimal places. |
| `lat-hemisphere` | `"N" \| "S" \| null` | Полушарие широты. |
| `longitude` | `number` | Долгота, **7** decimal places. |
| `lon-hemisphere` | `"E" \| "W" \| null` | Полушарие долготы. |
| `speed` | `number` | Скорость **км/ч**, **1** decimal place. |
| `direction` | `number` | Курс (°), **1** decimal place. |
| `mode` | `"E" \| "D" \| "A" \| "N" \| null` | Режим. |
| `satellites-count` | `integer` | Число спутников. |
| `source` | `string \| null` | Составной id источника (см. ниже). |
| `quality` / `nav-quality` | см. ниже | Режим достоверности. |

### Поле `source`

Единый формат на legacy, `/v1/` и `/v2/`:

| Значение | Провайдер (`provider` filter) | Смысл |
|----------|-------------------------------|--------|
| `nmea/rmc` | `nmea` | Принятое GNRMC |
| `nmea/ecef` | `nmea` | ECEFPOSVEL |
| `nmea/fusion` | `nmea` | Predict / coast fusion |
| `qr` | `qr` | QR→координаты (будущий провайдер) |
| `imu` | `imu` | Акселерометр / IMU (будущий) |
| `triangulation` | `triangulation` | Триангуляция оператора (будущий) |

Фильтр query `provider` матчит сегмент `source` до `/` (или весь `source`, если слэша нет).

`quality` в JSON (kebab на v1/v2: после `_json_keys_to_kebab` остаётся `quality`): `"GOOD" \| "KF_ECEF" \| "COAST" \| "DEGRADED" \| "LOST" \| null`.

При `quality` = `LOST` новые точки в кэш не публикуются; `last-coords` возвращает последнюю доступную запись до потери сигнала.

### Fusion: конфигурация (`[Navigation]`)

| Ключ | Значения | По умолчанию | Описание |
|------|----------|--------------|----------|
| `PublishMode` | `measurement` \| `timer` \| `hybrid` | `measurement` | см. plan |
| `OutputRateHz` | 1–20 | `10` | Частота predict / timer publish |
| `Profile` | `tram` \| `bus` \| `custom` | `tram` | Секция `VehicleProfiles.toml` |

`[API].Workers` должен быть **1**.

### Провайдеры (`[Sources.<name>]`)

| Секция | Type | Поля |
|--------|------|------|
| `[Sources.nmea]` | `serial-nmea` | `HardwarePort`, `Baud` (+ `[System].Input` / `Stdin`) |
| `[Sources.qr-geo]` | `qr-geo` | stub |
| `[Sources.imu]` | `imu` | stub |
| `[Sources.triangulation]` | `triangulation-http` | stub: `Url`, `IntervalMs`, `TimeoutMs` |

Legacy `[Hardware]` без `[Sources.nmea]` по-прежнему читается как включённый nmea.

## 4. Эндпоинты poll (`/api/navigator/v1/`)

### 4.1 GET /api/ping

Проверка доступности.

```bash
curl -s "http://127.0.0.1:7000/api/ping"
```

```json
{
  "running": "OK",
  "timestamp-utc": "2026-03-29T12:34:56.789+00:00"
}
```

### 4.2 GET /api/navigator/v1/last-coords

Последняя запись кэша (любой провайдер). Формат:

```json
{
  "result": true,
  "record": {
    "record-id": 0,
    "time": "2026-04-10T10:15:00+00:00",
    "is-valid": "A",
    "latitude": 46.05123,
    "lat-hemisphere": "N",
    "longitude": 14.50678,
    "lon-hemisphere": "E",
    "speed": 0.8,
    "direction": 176.5,
    "mode": "A",
    "satellites-count": 9,
    "source": "nmea/rmc",
    "quality": "GOOD"
  }
}
```

Нет данных: `{"result": false, "error": "no data"}`.

### 4.3 GET /api/navigator/v1/all-coords

- `limit` (`integer`, optional, default `10`, range `1..1000`)

### 4.4 DELETE /api/navigator/v1/delete-record/{record_id}

Удаляет запись в SQLite; кэш не очищается.

## 5. Эндпоинты `/api/navigator/v2/`

### 5.1 SSE GET /api/navigator/v2/last-coords

Поток обновлений последней точки. Query (опционально): `provider`.

- Media type: `text/event-stream`
- **Координаты:** без имени события — только `data:` + JSON **в формате тела** `GET /api/navigator/v1/last-coords`.
- При connect — сразу текущий last (или `result:false`).
- Далее — каждый новый publish в Hub, прошедший фильтр `provider`.
- **Keepalive:** если пауза между отправками больше `[API].SseKeepaliveSec` (по умолчанию 15) — кадр:

```
event: ping
data: {}

```

Пример:

```bash
curl -N "http://127.0.0.1:7000/api/navigator/v2/last-coords?provider=nmea"
```

```
data: {"result":true,"record":{"record-id":0,"source":"nmea/rmc",...}}

event: ping
data: {}

```

### 5.2 GET /api/navigator/v2/all-coords

Выборка до **1000** точек (новее → старее). Все query-параметры опциональны:

| Параметр | Описание |
|----------|----------|
| `provider` | Фильтр семейства (`nmea`, `qr`, …) |
| `from` | ISO8601 UTC — нижняя граница `time` |
| `to` | ISO8601 UTC — верхняя граница `time` |

Без `provider` — все источники. Невалидные `from`/`to` → `400`.

```bash
curl -s "http://127.0.0.1:7000/api/navigator/v2/all-coords?provider=nmea&from=2026-04-10T10:00:00+00:00"
```

Ответ: `{ "result": true, "count": N, "data": [ ... ] }` (kebab-case).

## 6. Коды ответа

- `200 OK` — успех (включая «не найдено» для delete).
- `400 Bad Request` — невалидные `from`/`to`.
- `422 Unprocessable Entity` — неверные параметры (например `limit`).
- `500 Internal Server Error` — внутренняя ошибка.
- `401 Unauthorized` — legacy без валидного Bearer.

## 7. Версионирование

Изменения, ломающие совместимость полей или путей, оформляются новой версией протокола.

Краткий обзор: [README.md](../README.md).
