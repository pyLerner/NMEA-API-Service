# -*- coding: utf-8 -*-
# =============================================================================
# NavFusion v2: онлайн GNRMC + ECEFPOSVEL, Kalman CV в локальной ENU (UTF-8)
# =============================================================================
"""
Слой fusion: gated Kalman constant-velocity в ENU.

Спецификация: plan/KALMAN-ECEF-FUSION-v2.md

Основные возможности v2:
- гейты kinematic от последнего seen RMC (dt >= 0.5 с);
- hard reset для доверенного RMC (mode in RmcTrustModes);
- standstill и обнуление скорости на стоянке в ingest_rmc;
- speed/direction в API из полей RMC/ECEF при GOOD;
- predict внутренний; публикация по PublishMode.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from models.data_models import VehicleProfile
from navigation.enums import NavQuality, NavSource, PublishMode
from navigation.geo import (
    enu_to_latlon,
    haversine_m,
    hemi_from_signed,
    latlon_to_enu,
    signed_lat_lon,
)

KMH_TO_MS = 1.0 / 3.6
V_MIN_REVERSE_MS = 1.0
RMC_GATE_MIN_DT_SEC = 0.5


@dataclass
class FusionOutput:
    """Запись координат на выходе NavFusion для кэша и API."""

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
    source: str
    quality: str


class NavFusion:
    """
    Gated Kalman CV-фильтр в ENU с якорем на последнем хорошем RMC.

    Параметры
    ----------
    profile : VehicleProfile
        Лимиты гейтов и стоянки из VehicleProfiles.toml.
    publish_mode : PublishMode
        Политика записи в кэш (measurement | timer | hybrid).
    logger : logging.Logger, optional
        Для WARNING при hard reset к RMC.
    """

    def __init__(
        self,
        profile: VehicleProfile,
        publish_mode: PublishMode = PublishMode.MEASUREMENT,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._p = profile
        self._publish_mode = publish_mode
        self._logger = logger
        self._v_max_ms = profile.v_max_kmh * KMH_TO_MS

        self._initialized = False
        self._anchor_lat = 0.0
        self._anchor_lon = 0.0
        self._x = [0.0, 0.0, 0.0, 0.0]  # E, N, vE, vN
        self._p_diag = [25.0, 25.0, 4.0, 4.0]

        self._last_pub_lat: Optional[float] = None
        self._last_pub_lon: Optional[float] = None
        self._last_pub_mono = 0.0

        self._last_rmc_lat: Optional[float] = None
        self._last_rmc_lon: Optional[float] = None
        self._last_rmc_mono = 0.0

        self._last_accept_lat: Optional[float] = None
        self._last_accept_lon: Optional[float] = None
        self._last_accept_mono = 0.0

        self._last_meas_speed = 0.0
        self._last_meas_direction = 0.0
        self._last_nonzero_direction = 0.0

        self._last_good_mono = 0.0
        self._last_rmc_seen_mono = 0.0
        self._last_predict_mono = 0.0

        self._quality: NavQuality = NavQuality.LOST
        self._source: NavSource = NavSource.FUSION
        self._mode: Optional[str] = None
        self._satellites = 0

        self._standstill_sec = 0.0
        self._frozen = False
        self._reject_streak = 0

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def last_rmc_mono(self) -> float:
        return self._last_rmc_seen_mono

    @property
    def quality(self) -> NavQuality:
        return self._quality

    def note_rmc_seen(self) -> None:
        self._last_rmc_seen_mono = time.monotonic()

    def _is_trusted_rmc(self, rec: dict[str, Any]) -> bool:
        if rec.get("is_valid") != "A":
            return False
        mode = rec.get("mode")
        return mode is None or mode in self._p.rmc_trust_modes

    def _kinematic_gates_fail(
        self, lat: float, lon: float, dt: float
    ) -> bool:
        if self._last_rmc_lat is None or self._last_rmc_mono <= 0:
            return False
        dist = haversine_m(self._last_rmc_lat, self._last_rmc_lon, lat, lon)
        v_impl = dist / dt
        if v_impl > self._v_max_ms:
            return True
        if self._x[2] or self._x[3]:
            v_prev = math.hypot(self._x[2], self._x[3])
            if abs(v_impl - v_prev) / dt > self._p.a_max:
                return True
            if v_prev > V_MIN_REVERSE_MS:
                de = latlon_to_enu(
                    lat, lon, self._last_rmc_lat, self._last_rmc_lon
                )
                dot = de[0] * self._x[2] + de[1] * self._x[3]
                if dot < 0:
                    return True
        return False

    def _hard_reset_to_rmc(
        self, lat: float, lon: float, rec: dict[str, Any], drift_m: float
    ) -> None:
        if self._logger is not None:
            self._logger.warning(
                "Trusted RMC hard reset: drift=%.1fm mode=%s",
                drift_m,
                rec.get("mode"),
            )
        e, n = latlon_to_enu(lat, lon, self._anchor_lat, self._anchor_lon)
        if drift_m > self._p.innov_gate_min_m:
            self._anchor_lat, self._anchor_lon = lat, lon
            e, n = 0.0, 0.0
        self._x[0], self._x[1] = e, n
        speed_kmh = float(rec.get("speed") or 0.0)
        if speed_kmh < self._p.rmc_speed_zero_kmh:
            self._x[2] = self._x[3] = 0.0
        else:
            direction = float(rec.get("direction") or 0.0)
            v_ms = speed_kmh * KMH_TO_MS
            rad = math.radians(direction)
            self._x[2] = v_ms * math.sin(rad)
            self._x[3] = v_ms * math.cos(rad)
        self._p_diag = [4.0, 4.0, 1.0, 1.0]
        self._quality = NavQuality.GOOD
        self._source = NavSource.NMEA
        self._reject_streak = 0

    def ingest_rmc(self, rec: dict[str, Any]) -> Optional[FusionOutput]:
        """
        Обработать GNRMC: гейты, standstill, Kalman-update или hard reset.

        Returns
        -------
        FusionOutput | None
            Запись для кэша при публикации; None при reject в режиме measurement.
        """
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

        gate_dt = RMC_GATE_MIN_DT_SEC
        if self._last_rmc_mono > 0:
            gate_dt = max(now - self._last_rmc_mono, RMC_GATE_MIN_DT_SEC)

        gates_fail = False
        if self._initialized and self._last_rmc_lat is not None:
            gates_fail = self._kinematic_gates_fail(lat, lon, gate_dt)

        trusted = self._is_trusted_rmc(rec)
        drift_m = 0.0
        if self._last_rmc_lat is not None:
            drift_m = haversine_m(self._last_rmc_lat, self._last_rmc_lon, lat, lon)

        if gates_fail and trusted:
            self._hard_reset_to_rmc(lat, lon, rec, drift_m)
            self._apply_accepted_rmc(lat, lon, rec, now, is_valid)
            self._note_rmc_position(lat, lon, now)
            return self._maybe_publish(now, rec.get("datetime"))

        if gates_fail:
            self._reject_streak += 1
            self._refresh_quality(now, rmc_present=True, rejected=True)
            self._note_rmc_position(lat, lon, now)
            if self._publish_mode == PublishMode.TIMER:
                return self._maybe_publish(now, rec.get("datetime"))
            return None

        if not self._initialized:
            self._anchor_lat, self._anchor_lon = lat, lon
            self._x = [0.0, 0.0, 0.0, 0.0]
            self._p_diag = [4.0, 4.0, 1.0, 1.0]
            self._initialized = True
        else:
            e, n = latlon_to_enu(lat, lon, self._anchor_lat, self._anchor_lon)
            inflate = self._p.rmc_invalid_inflate if is_valid == "V" else 1.0
            self._kalman_update_position(e, n, pos_var=4.0 * inflate)

        self._apply_accepted_rmc(lat, lon, rec, now, is_valid)
        self._note_rmc_position(lat, lon, now)
        return self._maybe_publish(now, rec.get("datetime"))

    def _apply_accepted_rmc(
        self,
        lat: float,
        lon: float,
        rec: dict[str, Any],
        now: float,
        is_valid: str,
    ) -> None:
        dist_accept = 0.0
        dt_accept = 1.0
        if self._last_accept_mono > 0 and self._last_accept_lat is not None:
            dist_accept = haversine_m(
                self._last_accept_lat, self._last_accept_lon, lat, lon
            )
            dt_accept = max(now - self._last_accept_mono, RMC_GATE_MIN_DT_SEC)

        self._update_standstill(dist_accept, dt_accept)

        speed_kmh = float(rec.get("speed") or 0.0)
        direction = float(rec.get("direction") or 0.0)
        self._last_meas_speed = speed_kmh
        self._last_meas_direction = direction
        if direction != 0.0:
            self._last_nonzero_direction = direction

        if (
            speed_kmh < self._p.rmc_speed_zero_kmh
            and dist_accept < self._p.standstill_pos_m
        ):
            self._x[2] = self._x[3] = 0.0
        elif not self._frozen:
            self._update_velocity_from_rmc_delta(lat, lon, dt_accept)

        self._last_accept_lat, self._last_accept_lon = lat, lon
        self._last_accept_mono = now
        self._last_good_mono = now
        self._quality = NavQuality.GOOD
        self._source = NavSource.NMEA
        self._reject_streak = 0
        self._last_predict_mono = now

    def _note_rmc_position(self, lat: float, lon: float, now: float) -> None:
        self._last_rmc_lat, self._last_rmc_lon = lat, lon
        self._last_rmc_mono = now

    def _update_velocity_from_rmc_delta(
        self, lat: float, lon: float, dt: float
    ) -> None:
        if self._last_accept_lat is None or self._last_accept_mono <= 0:
            return
        de, dn = latlon_to_enu(
            lat, lon, self._last_accept_lat, self._last_accept_lon
        )
        self._x[2] = de / dt
        self._x[3] = dn / dt

    def ingest_ecef(self, rec: dict[str, Any]) -> Optional[FusionOutput]:
        """
        Обработать ECEFPOSVEL при паузе GNRMC (t_since_rmc > 1 с, в пределах t_hold).

        Returns
        -------
        FusionOutput | None
            Запись при accept или timer/hybrid publish; иначе None.
        """
        if not self._initialized:
            return None
        if rec.get("is_valid") != "A":
            return None

        now = time.monotonic()
        t_since_rmc = (
            now - self._last_rmc_seen_mono
            if self._last_rmc_seen_mono
            else float("inf")
        )
        if t_since_rmc <= 1.0:
            return None

        lat, lon = signed_lat_lon(
            rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"]
        )
        e, n = latlon_to_enu(lat, lon, self._anchor_lat, self._anchor_lon)

        dt_meas = (
            max(now - self._last_predict_mono, RMC_GATE_MIN_DT_SEC)
            if self._last_predict_mono
            else 1.0
        )
        self._predict_internal(min(dt_meas, 1.0))

        dist = 0.0
        if self._last_accept_lat is not None and self._last_accept_mono > 0:
            dist = haversine_m(self._last_accept_lat, self._last_accept_lon, lat, lon)
            dt_gate = max(now - self._last_accept_mono, RMC_GATE_MIN_DT_SEC)
            if dist / dt_gate > self._v_max_ms:
                self._refresh_quality(now, rmc_present=False, rejected=True)
                return self._publish_if_timer(now, rec.get("datetime"))

        if self._frozen and dist > self._p.frozen_jump_m:
            self._refresh_quality(now, rmc_present=False, rejected=True)
            return self._publish_if_timer(now, rec.get("datetime"))

        if t_since_rmc > self._p.t_hold_sec:
            self._refresh_quality(now, rmc_present=False)
            return self._publish_if_timer(now, rec.get("datetime"))

        if not self._ecef_innovation_ok(e, n):
            self._quality = NavQuality.COAST
            self._source = NavSource.FUSION
            return self._publish_if_timer(now, rec.get("datetime"))

        self._kalman_update_position(e, n, pos_var=9.0)
        self._last_good_mono = now
        self._quality = NavQuality.KF_ECEF
        self._source = NavSource.ECEF
        self._last_meas_speed = float(rec.get("speed") or 0.0)
        self._last_meas_direction = float(rec.get("direction") or 0.0)
        if self._last_meas_direction != 0.0:
            self._last_nonzero_direction = self._last_meas_direction
        self._last_accept_lat, self._last_accept_lon = lat, lon
        self._last_accept_mono = now
        self._update_standstill(dist, dt_meas)
        self._last_predict_mono = now
        return self._maybe_publish(now, rec.get("datetime"))

    def predict_internal_only(self, dt: float) -> None:
        """Внутренний шаг predict Kalman без записи в кэш."""
        if not self._initialized:
            return
        now = time.monotonic()
        self._predict_internal(dt)
        self._refresh_quality(now, rmc_present=False)
        self._last_predict_mono = now
        if self._quality == NavQuality.DEGRADED:
            self._decay_velocity(dt)

    def should_publish_timer(self) -> bool:
        """
        Нужно ли публиковать текущее состояние по таймеру.

        True для timer всегда (если не LOST); для hybrid — при quality != GOOD
        и паузе RMC > 1 с.
        """
        if not self._initialized or self._quality == NavQuality.LOST:
            return False
        if self._publish_mode == PublishMode.TIMER:
            return True
        if self._publish_mode == PublishMode.HYBRID:
            if self._quality == NavQuality.GOOD:
                return False
            t_since_rmc = (
                time.monotonic() - self._last_rmc_seen_mono
                if self._last_rmc_seen_mono
                else float("inf")
            )
            return t_since_rmc > 1.0
        return False

    def build_publish_output(
        self, dt_iso: Optional[str] = None
    ) -> Optional[FusionOutput]:
        """Собрать FusionOutput из текущего состояния (после predict-тика)."""
        if not self._initialized or self._quality == NavQuality.LOST:
            return None
        return self._maybe_publish(time.monotonic(), dt_iso)

    def predict_publish(self, dt: float, dt_iso: Optional[str] = None) -> Optional[FusionOutput]:
        """Legacy: predict + publish (timer mode)."""
        self.predict_internal_only(dt)
        if self._quality == NavQuality.LOST:
            return None
        return self._maybe_publish(time.monotonic(), dt_iso)

    def _publish_if_timer(
        self, now: float, dt_iso: Optional[str]
    ) -> Optional[FusionOutput]:
        if self._publish_mode in (PublishMode.TIMER, PublishMode.HYBRID):
            return self._maybe_publish(now, dt_iso)
        return None

    def _maybe_publish(self, now: float, dt_iso: Optional[str]) -> Optional[FusionOutput]:
        if not self._initialized or self._quality == NavQuality.LOST:
            return None
        lat, lon = enu_to_latlon(self._x[0], self._x[1], self._anchor_lat, self._anchor_lon)
        speed, direction = self._build_output_speed_course(lat, lon, now)
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
            is_valid="A" if self._quality == NavQuality.GOOD else "V",
            mode=self._mode,
            satellites_count=self._satellites,
            source=self._source.value,
            quality=self._quality.value,
        )

    def _build_output_speed_course(
        self, lat: float, lon: float, now: float
    ) -> tuple[float, float]:
        if self._frozen:
            return 0.0, self._last_nonzero_direction

        if self._quality == NavQuality.GOOD and self._source == NavSource.NMEA:
            return round(self._last_meas_speed, 1), round(self._last_meas_direction, 1)

        if self._quality == NavQuality.KF_ECEF and self._source == NavSource.ECEF:
            return round(self._last_meas_speed, 1), round(self._last_meas_direction, 1)

        if self._quality in (NavQuality.COAST, NavQuality.DEGRADED):
            if self._last_accept_lat is not None and self._last_accept_mono > 0:
                dt = max(now - self._last_accept_mono, RMC_GATE_MIN_DT_SEC)
                dist = haversine_m(
                    self._last_accept_lat, self._last_accept_lon, lat, lon
                )
                speed_kmh = (dist / dt) * 3.6
                de, dn = latlon_to_enu(
                    lat, lon, self._last_accept_lat, self._last_accept_lon
                )
                if abs(de) < 1e-6 and abs(dn) < 1e-6:
                    return round(speed_kmh, 1), self._last_nonzero_direction
                direction = (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0
                return round(speed_kmh, 1), round(direction, 1)

        if self._publish_mode == PublishMode.TIMER:
            return self._speed_course(lat, lon, now)

        v_ms = math.hypot(self._x[2], self._x[3])
        if v_ms < 1e-6:
            return 0.0, self._last_nonzero_direction
        direction = (math.degrees(math.atan2(self._x[2], self._x[3])) + 360.0) % 360.0
        return round(v_ms * 3.6, 1), round(direction, 1)

    def _speed_course(self, lat: float, lon: float, now: float) -> tuple[float, float]:
        if self._last_pub_lat is None or self._last_pub_mono <= 0:
            v_ms = math.hypot(self._x[2], self._x[3])
            return round(v_ms * 3.6, 1), 0.0
        dt = max(now - self._last_pub_mono, 0.05)
        dist = haversine_m(self._last_pub_lat, self._last_pub_lon, lat, lon)
        speed_kmh = (dist / dt) * 3.6
        de, dn = latlon_to_enu(lat, lon, self._last_pub_lat, self._last_pub_lon)
        if abs(de) < 1e-6 and abs(dn) < 1e-6:
            return round(speed_kmh, 1), 0.0
        direction = (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0
        return round(speed_kmh, 1), round(direction, 1)

    def _refresh_quality(
        self,
        now: float,
        *,
        rmc_present: bool,
        rejected: bool = False,
    ) -> None:
        if rejected:
            if self._reject_streak >= 3:
                self._quality = NavQuality.DEGRADED
            else:
                self._quality = NavQuality.COAST

        t_since_rmc = (
            now - self._last_rmc_seen_mono
            if self._last_rmc_seen_mono
            else float("inf")
        )
        t_since_good = (
            now - self._last_good_mono if self._last_good_mono else float("inf")
        )
        if t_since_good > self._p.t_lost_sec:
            self._quality = NavQuality.LOST
        elif t_since_rmc > self._p.t_hold_sec:
            if self._quality != NavQuality.LOST:
                self._quality = NavQuality.DEGRADED
        elif not rejected and self._quality not in (
            NavQuality.GOOD,
            NavQuality.KF_ECEF,
        ):
            if not (rmc_present and self._quality == NavQuality.GOOD):
                self._quality = NavQuality.COAST

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
        if not self._frozen:
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
