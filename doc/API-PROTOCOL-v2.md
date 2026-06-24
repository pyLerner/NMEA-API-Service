# API-PROTOCOL-v2

Протокол HTTP API сервиса `NMEA-API-Service` версии `v2`.

## 1. Общие положения

- Базовый URL формируется из параметров `[API].Host` и `[API].HTTP_Port`.
- Запросы с телом: заголовок `Content-Type: application/json`.
- Ответы: JSON в кодировке UTF-8.
- Ключи JSON в успешных ответах данных: **kebab-case** (например `record-id`, `lat-hemisphere`, `satellites-count`).
- Версия в пути: префикс `/api/navigator/v1/` для эндпоинтов данных; **исключение** — проверка доступности без этого префикса: `GET /api/ping`.
- **Авторизация:** все эндпоинты, описанные в этом документе как контракт v2, **не** требуют заголовка `Authorization` и работают без Bearer-токена.

Текущий набор эндпоинтов v2:

- `GET /api/ping`
- `GET /api/navigator/v1/last-coords`
- `GET /api/navigator/v1/all-coords`
- `DELETE /api/navigator/v1/delete-record/{record_id}`

Имена сегментов пути после `/api/navigator/v1/` соответствуют kebab-case-именам прежних эндпоинтов (`LastCoords` → `last-coords` и т.д.).

**Не входят в контракт v2:** служебные URL FastAPI (`/docs`, `/openapi.json`, `/redoc` и т.п.). На них распространяется общий middleware: без корректного `Authorization: Bearer` ответ будет `401 Unauthorized`, как для legacy-эндпоинтов. Для проверки доступности сервиса без токена используйте `GET /api/ping`.

## 2. Legacy v1 (обратная совместимость)

Предыдущие пути и контракт с **обязательной** Bearer-аутентификацией сохранены без изменений поведения:

- `GET /LastCoords`
- `GET /AllCoords`
- `DELETE /DeleteRecord/{record_id}`

Формат JSON legacy: ключи как в [API-PROTOCOL-v1.md](API-PROTOCOL-v1.md) (`record_id`, `lat_hemisphere`, …).

## 3. Формат данных записи (v2)

Те же семантические поля, что в v1, с ключами в kebab-case:

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
| `source` | `"nmea" \| "ecef" \| "fusion" \| null` | Источник последнего измерения, повлиявшего на точку. |
| `nav-quality` | `"GOOD" \| "KF_ECEF" \| "COAST" \| "DEGRADED" \| "LOST" \| null` | Режим fusion-слоя (см. `plan/KALMAN-ECEF-PLAN.md`). `null` — legacy-запись до fusion. |

При `nav-quality` = `LOST` новые точки в кэш не публикуются; `last-coords` возвращает последнюю доступную запись до потери сигнала.

## 4. Эндпоинты

### 4.1 GET /api/ping

Проверка доступности сервиса.

#### Ответ `200 OK`

| Поле | Тип | Описание |
|------|-----|----------|
| `running` | `string` | При успехе: `"OK"`. |
| `timestamp-utc` | `string` | Время в UTC (ISO 8601, суффикс `+00:00`). |

#### Запрос

```bash
curl -s "http://127.0.0.1:7000/api/ping"
```

#### Пример ответа

```json
{
  "running": "OK",
  "timestamp-utc": "2026-03-29T12:34:56.789+00:00"
}
```

### 4.2 GET /api/navigator/v1/last-coords

Возвращает последнюю запись из in-memory кэша (логика совпадает с legacy `GET /LastCoords`).

#### Запрос

```bash
curl -s "http://127.0.0.1:7000/api/navigator/v1/last-coords"
```

#### Успех (есть данные)

- HTTP статус: `200 OK`

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
    "satellites-count": 9
  }
}
```

#### Успех (данных нет)

- HTTP статус: `200 OK`

```json
{"result": false, "error": "no data"}
```

### 4.3 GET /api/navigator/v1/all-coords

Возвращает список записей с учётом `limit` (логика совпадает с legacy `GET /AllCoords`).

#### Параметры запроса

- `limit` (`integer`, optional, default `10`, range `1..1000`)

#### Запрос

```bash
curl -s "http://127.0.0.1:7000/api/navigator/v1/all-coords?limit=100"
```

#### Успех

- HTTP статус: `200 OK`

```json
{
  "result": true,
  "count": 2,
  "data": [
    {
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
      "satellites-count": 9
    },
    {
      "record-id": 124,
      "time": "2026-04-10T10:14:59+00:00",
      "is-valid": "A",
      "latitude": 46.05111,
      "lat-hemisphere": "N",
      "longitude": 14.50655,
      "lon-hemisphere": "E",
      "speed": 0.7,
      "direction": 175.9,
      "mode": "A",
      "satellites-count": 9
    }
  ]
}
```

#### Ошибка валидации параметров

Если `limit` вне диапазона:

- HTTP статус: `422 Unprocessable Entity`
- Формат тела — стандартный для FastAPI (вложенная структура `detail`; ключи могут не следовать kebab-case).

### 4.4 DELETE /api/navigator/v1/delete-record/{record_id}

Удаляет запись по `record_id` (`key_id`) в SQLite. Кэш in-memory не очищается.

#### Параметры пути

- `record_id` (`integer`, required) — числовой идентификатор в пути (как в v1).

#### Запрос

```bash
curl -s -X DELETE "http://127.0.0.1:7000/api/navigator/v1/delete-record/124"
```

#### Успех (удалено)

- HTTP статус: `200 OK`

```json
{"result": true, "detail": "record 124 deleted"}
```

#### Успех (не найдено)

- HTTP статус: `200 OK`

```json
{"result": false, "detail": "record 124 not found"}
```

#### Внутренняя ошибка

- HTTP статус: `500 Internal Server Error`

```json
{"detail": "<error_text>"}
```

## 5. Коды ответа (v2)

- `200 OK` — успешная обработка запроса (включая сценарий «не найдено» для delete).
- `422 Unprocessable Entity` — неверные параметры запроса.
- `500 Internal Server Error` — внутренняя ошибка обработки.

Для legacy v1 дополнительно возможен `401 Unauthorized` — см. [API-PROTOCOL-v1.md](API-PROTOCOL-v1.md).

## 6. Версионирование

Этот документ описывает контракт `v2`. Изменения, ломающие совместимость полей или путей, оформляются новой версией протокола и отдельным файлом `API-PROTOCOL-vN.md`.

Краткий обзор запуска, тестов и структуры репозитория: [README.md](../README.md).
