# -*- coding: utf-8 -*-
"""Нормализация и валидация записей qr_geo (N/E only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qr_geo.models import QrGeoEntry

MAX_QR_VALUE_LEN = 256
MAX_LABEL_LEN = 512
MAX_ROWS = 20_000
MAX_FILE_BYTES = 10 * 1024 * 1024


@dataclass
class FieldError:
    """Ошибка одного поля / строки файла."""

    row: int
    field: str
    message: str
    qr_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "row": self.row,
            "field": self.field,
            "message": self.message,
        }
        if self.qr_value is not None:
            out["qr-value"] = self.qr_value
        return out


def strip_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "«", "»"):
        return text[1:-1].strip()
    if text.startswith("«") and text.endswith("»"):
        return text[1:-1].strip()
    return text


def normalize_coord_string(raw: Any) -> str:
    """Подготовить строку числа: trim, кавычки, десятичная запятая → точка."""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    text = strip_quotes(str(raw))
    text = text.replace("\u00a0", "").replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return text


def parse_coord(raw: Any, field: str) -> tuple[float | None, str | None]:
    """Вернуть (float, None) или (None, error_message)."""
    if isinstance(raw, bool):
        return None, f"invalid {field}: boolean not allowed"
    if isinstance(raw, (int, float)):
        return float(raw), None
    text = normalize_coord_string(raw)
    if not text:
        return None, f"missing {field}"
    if text.count(".") > 1 or "," in text:
        return None, f"invalid number after normalize: {raw!r}"
    try:
        return float(text), None
    except ValueError:
        return None, f"invalid number after normalize: {raw!r}"


def _parse_enabled(raw: Any) -> tuple[bool | None, str | None]:
    if raw is None or raw == "":
        return True, None
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw in (0, 1):
            return bool(raw), None
        return None, f"invalid enabled: {raw!r}"
    text = strip_quotes(str(raw)).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return True, None
    if text in ("0", "false", "no", "n"):
        return False, None
    return None, f"invalid enabled: {raw!r}"


def _hemi(raw: Any, allowed: frozenset[str], default: str, field: str) -> tuple[str | None, str | None]:
    if raw is None or raw == "":
        return default, None
    text = strip_quotes(str(raw)).strip().upper()
    if text not in allowed:
        return None, f"invalid {field}: expected one of {sorted(allowed)}, got {raw!r}"
    return text, None


def validate_entry(raw: dict[str, Any], row: int) -> tuple[QrGeoEntry | None, list[FieldError]]:
    """Валидировать одну сырую запись (ключи snake или kebab)."""
    errors: list[FieldError] = []

    def get(*names: str) -> Any:
        for name in names:
            if name in raw and raw[name] is not None:
                return raw[name]
        return None

    qr_raw = get("qr-value", "qr_value", "qrValue")
    qr_value = strip_quotes(str(qr_raw)) if qr_raw is not None else ""
    if not qr_value:
        errors.append(FieldError(row=row, field="qr-value", message="missing qr-value"))
    elif len(qr_value) > MAX_QR_VALUE_LEN:
        errors.append(
            FieldError(
                row=row,
                field="qr-value",
                message=f"qr-value longer than {MAX_QR_VALUE_LEN}",
                qr_value=qr_value[:64],
            )
        )

    lat, lat_err = parse_coord(get("latitude", "lat"), "latitude")
    if lat_err:
        errors.append(FieldError(row=row, field="latitude", message=lat_err, qr_value=qr_value or None))
    elif lat is not None and (lat < 0 or lat > 90):
        errors.append(
            FieldError(
                row=row,
                field="latitude",
                message=f"latitude out of range [0, 90]: {lat}",
                qr_value=qr_value or None,
            )
        )

    lon, lon_err = parse_coord(get("longitude", "lon", "lng"), "longitude")
    if lon_err:
        errors.append(FieldError(row=row, field="longitude", message=lon_err, qr_value=qr_value or None))
    elif lon is not None and (lon < 0 or lon > 180):
        errors.append(
            FieldError(
                row=row,
                field="longitude",
                message=f"longitude out of range [0, 180]: {lon}",
                qr_value=qr_value or None,
            )
        )

    lat_hemi, hemi_err = _hemi(
        get("lat-hemisphere", "lat_hemisphere", "lat_hemi"),
        frozenset({"N"}),
        "N",
        "lat-hemisphere",
    )
    if hemi_err:
        errors.append(FieldError(row=row, field="lat-hemisphere", message=hemi_err, qr_value=qr_value or None))

    lon_hemi, lon_hemi_err = _hemi(
        get("lon-hemisphere", "lon_hemisphere", "lon_hemi"),
        frozenset({"E"}),
        "E",
        "lon-hemisphere",
    )
    if lon_hemi_err:
        errors.append(
            FieldError(row=row, field="lon-hemisphere", message=lon_hemi_err, qr_value=qr_value or None)
        )

    enabled, en_err = _parse_enabled(get("enabled"))
    if en_err:
        errors.append(FieldError(row=row, field="enabled", message=en_err, qr_value=qr_value or None))

    label_raw = get("label")
    label: str | None = None
    if label_raw is not None and str(label_raw).strip() != "":
        label = strip_quotes(str(label_raw))
        if len(label) > MAX_LABEL_LEN:
            errors.append(
                FieldError(
                    row=row,
                    field="label",
                    message=f"label longer than {MAX_LABEL_LEN}",
                    qr_value=qr_value or None,
                )
            )

    if errors:
        return None, errors

    assert lat is not None and lon is not None
    assert lat_hemi is not None and lon_hemi is not None
    assert enabled is not None
    return (
        QrGeoEntry(
            qr_value=qr_value,
            latitude=lat,
            longitude=lon,
            lat_hemi=lat_hemi,
            lon_hemi=lon_hemi,
            label=label,
            enabled=enabled,
        ),
        [],
    )


def validate_all(rows: list[dict[str, Any]], *, row_offset: int = 1) -> tuple[list[QrGeoEntry], list[FieldError]]:
    """
    Валидировать список сырых записей.

    row_offset: 1 для CSV (после заголовка), 0 для JSON (0-based index в errors.row).
    """
    if len(rows) > MAX_ROWS:
        return [], [
            FieldError(
                row=0,
                field="file",
                message=f"too many rows: {len(rows)} > {MAX_ROWS}",
            )
        ]

    entries: list[QrGeoEntry] = []
    errors: list[FieldError] = []
    seen: dict[str, int] = {}

    for i, raw in enumerate(rows):
        row_no = i + row_offset
        entry, field_errors = validate_entry(raw, row_no)
        errors.extend(field_errors)
        if entry is None:
            continue
        if entry.qr_value in seen:
            errors.append(
                FieldError(
                    row=row_no,
                    field="qr-value",
                    message=f"duplicate in file (first at row {seen[entry.qr_value]})",
                    qr_value=entry.qr_value,
                )
            )
            continue
        seen[entry.qr_value] = row_no
        entries.append(entry)

    return entries, errors
