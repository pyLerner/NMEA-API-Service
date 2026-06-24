# =============================================================================
# NavFusion: online GNRMC + ECEFPOSVEL Kalman CV fusion in local ENU
# =============================================================================
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from models.data_models import VehicleProfile
from navigation.geo import (
    enu_to_latlon,
    haversine_m,
    hemi_from_signed,
    latlon_to_enu,
    signed_lat_lon,
)

Quality = Literal["GOOD", "KF_ECEF", "COAST", "DEGRADED", "LOST"]
Source = Literal["nmea", "ecef", "fusion"]

KMH_TO_MS = 1.0 / 3.6
V_MIN_REVERSE_MS = 1.0


@dataclass
class FusionOutput:
    datetime_iso: str
    latitude: float
    latitude_hemi: str
    longitude: float
    longitude_hemi: str
    speed: float
    direction: float
    is_valid: str
    mode: Optional[str]
    satellites_count: int
    source: Source
    quality: Quality


class NavFusion:
    """
    Gated Kalman constant-velocity filter in ENU anchored at last good RMC.

    Online only: no backfill. Publish via ``predict_publish`` (10 Hz timer)
    and after accepted measurement ingest.
    """

    def __init__(self, profile: VehicleProfile) -> None:
        self._p = profile
        self._v_max_ms = profile.v_max_kmh * KMH_TO_MS

        self._initialized = False
        self._anchor_lat = 0.0
        self._anchor_lon = 0.0
        self._x = [0.0, 0.0, 0.0, 0.0]  # E, N, vE, vN
        self._p_diag = [25.0, 25.0, 4.0, 4.0]

        self._last_pub_lat: Optional[float] = None
        self._last_pub_lon: Optional[float] = None
        self._last_pub_mono = 0.0
        self._last_good_mono = 0.0
        self._last_rmc_mono = 0.0
        self._last_predict_mono = 0.0

        self._quality: Quality = "LOST"
        self._source: Source = "fusion"
        self._mode: Optional[str] = None
        self._satellites = 0

        self._standstill_sec = 0.0
        self._frozen = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def last_rmc_mono(self) -> float:
        return self._last_rmc_mono

    def note_rmc_seen(self) -> None:
        self._last_rmc_mono = time.monotonic()

    def ingest_rmc(self, rec: dict[str, Any]) -> Optional[FusionOutput]:
        """Apply GNRMC measurement with gates. Returns output if published."""
        self.note_rmc_seen()
        lat, lon = signed_lat_lon(
            rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"]
        )
        if lat == 0.0 and lon == 0.0:
            return None

        now = time.monotonic()
        is_valid = rec.get("is_valid") or "V"
        self._satellites = int(rec.get("satellites_count") or 0)
        self._mode = rec.get("mode")

        accepted = True
        if self._initialized and self._last_pub_mono > 0:
            dt = max(now - self._last_pub_mono, 0.05)
            dist = haversine_m(self._last_pub_lat or lat, self._last_pub_lon or lon, lat, lon)
            v_impl = dist / dt
            if v_impl > self._v_max_ms:
                accepted = False
            elif self._x[2] or self._x[3]:
                v_prev = math.hypot(self._x[2], self._x[3])
                if abs(v_impl - v_prev) / dt > self._p.a_max:
                    accepted = False
                if v_prev > V_MIN_REVERSE_MS:
                    de = latlon_to_enu(lat, lon, self._last_pub_lat or lat, self._last_pub_lon or lon)
                    dot = de[0] * self._x[2] + de[1] * self._x[3]
                    if dot < 0:
                        accepted = False

        if not accepted:
            self._refresh_quality(now, rmc_present=True)
            return self._maybe_publish(now, rec.get("datetime"))

        if not self._initialized:
            self._anchor_lat, self._anchor_lon = lat, lon
            self._x = [0.0, 0.0, 0.0, 0.0]
            self._p_diag = [4.0, 4.0, 1.0, 1.0]
            self._initialized = True
        else:
            e, n = latlon_to_enu(lat, lon, self._anchor_lat, self._anchor_lon)
            inflate = self._p.rmc_invalid_inflate if is_valid == "V" else 1.0
            self._kalman_update_position(e, n, pos_var=4.0 * inflate)

        self._update_velocity_from_delta(lat, lon, now)
        self._last_good_mono = now
        self._quality = "GOOD"
        self._source = "nmea"
        self._standstill_sec = 0.0
        self._frozen = False
        self._last_predict_mono = now
        return self._maybe_publish(now, rec.get("datetime"))

    def ingest_ecef(self, rec: dict[str, Any]) -> Optional[FusionOutput]:
        """Apply ECEFPOSVEL when RMC is absent and within t_hold."""
        if not self._initialized:
            return None
        if rec.get("is_valid") != "A":
            return None

        now = time.monotonic()
        t_since_rmc = now - self._last_rmc_mono if self._last_rmc_mono else float("inf")
        if t_since_rmc <= 1.0:
            return None

        lat, lon = signed_lat_lon(
            rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"]
        )
        e, n = latlon_to_enu(lat, lon, self._anchor_lat, self._anchor_lon)

        dt_meas = max(now - self._last_predict_mono, 0.05) if self._last_predict_mono else 1.0
        self._predict_internal(min(dt_meas, 1.0))

        dist = haversine_m(
            self._last_pub_lat or lat, self._last_pub_lon or lon, lat, lon
        )
        if dist / dt_meas > self._v_max_ms:
            self._refresh_quality(now, rmc_present=False)
            return self._maybe_publish(now, rec.get("datetime"))

        if self._frozen and dist > self._p.frozen_jump_m:
            self._refresh_quality(now, rmc_present=False)
            return self._maybe_publish(now, rec.get("datetime"))

        if t_since_rmc > self._p.t_hold_sec:
            self._refresh_quality(now, rmc_present=False)
            return self._maybe_publish(now, rec.get("datetime"))

        if not self._ecef_innovation_ok(e, n):
            self._quality = "COAST"
            self._source = "fusion"
            return self._maybe_publish(now, rec.get("datetime"))

        self._kalman_update_position(e, n, pos_var=9.0)
        self._last_good_mono = now
        self._quality = "KF_ECEF"
        self._source = "ecef"
        self._update_standstill(dist, dt_meas)
        self._last_predict_mono = now
        return self._maybe_publish(now, rec.get("datetime"))

    def predict_publish(self, dt: float, dt_iso: Optional[str] = None) -> Optional[FusionOutput]:
        """Advance state by dt seconds and publish if not LOST."""
        if not self._initialized:
            return None
        now = time.monotonic()
        self._predict_internal(dt)
        self._refresh_quality(now, rmc_present=False)
        self._last_predict_mono = now
        if self._quality == "LOST":
            return None
        if self._quality == "DEGRADED":
            self._decay_velocity(dt)
        return self._maybe_publish(now, dt_iso)

    def _maybe_publish(self, now: float, dt_iso: Optional[str]) -> Optional[FusionOutput]:
        if not self._initialized or self._quality == "LOST":
            return None
        lat, lon = enu_to_latlon(self._x[0], self._x[1], self._anchor_lat, self._anchor_lon)
        speed, direction = self._speed_course(lat, lon, now)
        lat_a, lat_h, lon_a, lon_h = hemi_from_signed(lat, lon)
        iso = dt_iso or datetime.now(timezone.utc).isoformat()
        self._last_pub_lat, self._last_pub_lon = lat, lon
        self._last_pub_mono = now
        return FusionOutput(
            datetime_iso=iso,
            latitude=lat_a,
            latitude_hemi=lat_h,
            longitude=lon_a,
            longitude_hemi=lon_h,
            speed=speed,
            direction=direction,
            is_valid="A" if self._quality == "GOOD" else "V",
            mode=self._mode,
            satellites_count=self._satellites,
            source=self._source,
            quality=self._quality,
        )

    def _speed_course(self, lat: float, lon: float, now: float) -> tuple[float, float]:
        if self._last_pub_lat is None or self._last_pub_mono <= 0:
            v_ms = math.hypot(self._x[2], self._x[3])
            return v_ms * 3.6, 0.0
        dt = max(now - self._last_pub_mono, 0.05)
        dist = haversine_m(self._last_pub_lat, self._last_pub_lon, lat, lon)
        speed_kmh = (dist / dt) * 3.6
        de, dn = latlon_to_enu(lat, lon, self._last_pub_lat, self._last_pub_lon)
        if abs(de) < 1e-6 and abs(dn) < 1e-6:
            return speed_kmh, 0.0
        direction = (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0
        return speed_kmh, direction

    def _update_velocity_from_delta(self, lat: float, lon: float, now: float) -> None:
        if self._last_pub_lat is None or self._last_pub_mono <= 0:
            return
        dt = max(now - self._last_pub_mono, 0.05)
        de, dn = latlon_to_enu(lat, lon, self._last_pub_lat, self._last_pub_lon)
        self._x[2] = de / dt
        self._x[3] = dn / dt

    def _refresh_quality(self, now: float, *, rmc_present: bool) -> None:
        if rmc_present and self._quality == "GOOD":
            return
        t_since_rmc = now - self._last_rmc_mono if self._last_rmc_mono else float("inf")
        t_since_good = now - self._last_good_mono if self._last_good_mono else float("inf")
        if t_since_good > self._p.t_lost_sec:
            self._quality = "LOST"
        elif t_since_rmc > self._p.t_hold_sec:
            self._quality = "DEGRADED"
        elif self._quality not in ("GOOD", "KF_ECEF"):
            self._quality = "COAST"

    def _decay_velocity(self, dt: float) -> None:
        if self._frozen:
            self._x[2] = self._x[3] = 0.0
            return
        factor = max(0.0, 1.0 - dt / max(self._p.t_lost_sec, 1.0))
        self._x[2] *= factor
        self._x[3] *= factor

    def _update_standstill(self, dist: float, dt: float) -> None:
        if dist < self._p.standstill_pos_m:
            self._standstill_sec += dt
        else:
            self._standstill_sec = 0.0
            self._frozen = False
        if self._standstill_sec >= self._p.standstill_sec:
            self._frozen = True
            self._x[2] = self._x[3] = 0.0

    def _predict_internal(self, dt: float) -> None:
        if dt <= 0:
            return
        self._x[0] += self._x[2] * dt
        self._x[1] += self._x[3] * dt
        q_pos = 0.25 * self._p.a_max**2 * dt**4
        q_vel = self._p.a_max**2 * dt**2
        if self._frozen:
            q_pos *= 0.1
            q_vel *= 0.1
        self._p_diag[0] += q_pos
        self._p_diag[1] += q_pos
        self._p_diag[2] += q_vel
        self._p_diag[3] += q_vel

    def _kalman_update_position(self, z_e: float, z_n: float, pos_var: float) -> None:
        for i, z in enumerate((z_e, z_n)):
            p = self._p_diag[i]
            s = p + pos_var
            k = p / s
            y = z - self._x[i]
            self._x[i] += k * y
            self._p_diag[i] = (1 - k) * p

    def _ecef_innovation_ok(self, z_e: float, z_n: float) -> bool:
        thr = self._p.innov_gate_sigma
        min_m = self._p.innov_gate_min_m
        for i, z in enumerate((z_e, z_n)):
            p = self._p_diag[i]
            s = math.sqrt(p + 9.0)
            if abs(z - self._x[i]) > max(thr * s, min_m):
                return False
        return True
