#!/usr/bin/env python3
"""Full-file analysis of nmea-row-tram4.log: raw sources vs NavFusion replay."""
from __future__ import annotations

import re
import statistics
import sys
import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from models.data_models import _load_navigation_config
from navigation.fusion import NavFusion
from navigation.geo import haversine_m, signed_lat_lon
from nmea.parsing import ECEFPOSVEL_RE, GNRMC_RE, parse_ecefposvel, parse_rmc

LOG_PATH = ROOT / "debug" / "nmea-row-tram4.log"
TIME_KEY_RE = re.compile(r",(\d{6}\.\d{3}),")


@dataclass
class Point:
    t: datetime
    lat: float
    lon: float
    speed_field: float = 0.0
    quality: str = ""


@dataclass
class Metrics:
    rmc_intervals: list[float] = field(default_factory=list)
    ecef_intervals: list[float] = field(default_factory=list)
    rmc_ecef_same_sec_m: list[float] = field(default_factory=list)
    rmc_adj_m: list[float] = field(default_factory=list)
    ecef_adj_m: list[float] = field(default_factory=list)
    rmc_adj_spd: list[float] = field(default_factory=list)
    ecef_adj_spd: list[float] = field(default_factory=list)
    rmc_field_delta_spd: list[float] = field(default_factory=list)
    fusion_rmc_m: list[float] = field(default_factory=list)
    fusion_adj_m: list[float] = field(default_factory=list)
    fusion_adj_spd: list[float] = field(default_factory=list)
    fusion_intervals: list[float] = field(default_factory=list)
    quality_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rmc_gaps: list[float] = field(default_factory=list)
    rmc_n: int = 0
    ecef_n: int = 0
    fusion_n: int = 0
    fusion_lost_segments: int = 0


class SimClock:
    def __init__(self) -> None:
        self.t = 1_000_000.0
        self._last: datetime | None = None

    def monotonic(self) -> float:
        return self.t

    def advance_to(self, dt: datetime) -> None:
        if self._last is not None:
            d = (dt - self._last).total_seconds()
            if 0 < d < 7200:
                self.t += d
            elif d <= 0:
                self.t += 0.1
            else:
                self.t += 1.0
        self._last = dt


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def stats(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"n": 0, "mean": float("nan"), "median": float("nan"), "p95": float("nan"), "max": float("nan")}
    return {
        "n": float(len(vals)),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "p95": _pct(vals, 95),
        "max": max(vals),
    }


def _adj(series: list[Point], dist_out: list[float], spd_out: list[float], field_delta: list[float] | None = None) -> None:
    for i in range(1, len(series)):
        a, b = series[i - 1], series[i]
        dt = (b.t - a.t).total_seconds()
        if dt <= 0:
            continue
        d = haversine_m(a.lat, a.lon, b.lat, b.lon)
        dist_out.append(d)
        spd = (d / dt) * 3.6
        spd_out.append(spd)
        if field_delta is not None:
            field_delta.append(abs(b.speed_field - spd))


def _ecef_time_with_rmc_date(ecef_line: str, ref: datetime | None) -> datetime | None:
    rec = parse_ecefposvel(ecef_line)
    if not rec or not rec.get("datetime") or ref is None:
        return None
    ecef_dt = datetime.fromisoformat(rec["datetime"])
    return ref.replace(
        hour=ecef_dt.hour, minute=ecef_dt.minute, second=ecef_dt.second,
        microsecond=ecef_dt.microsecond,
    )


def parse_log(log_path: Path) -> tuple[list[Point], list[Point]]:
    rmc_pts: list[Point] = []
    ecef_pts: list[Point] = []
    last_rmc_dt: datetime | None = None

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if GNRMC_RE.match(s):
            rec = parse_rmc(s, None)
            if not rec or not rec.get("datetime"):
                continue
            lat, lon = signed_lat_lon(rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"])
            dt = datetime.fromisoformat(rec["datetime"])
            last_rmc_dt = dt
            rmc_pts.append(Point(dt, lat, lon, rec.get("speed") or 0.0))
        elif ECEFPOSVEL_RE.match(s):
            rec = parse_ecefposvel(s)
            if not rec or rec.get("is_valid") != "A":
                continue
            dt = _ecef_time_with_rmc_date(s, last_rmc_dt)
            if dt is None:
                continue
            lat, lon = signed_lat_lon(rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"])
            ecef_pts.append(Point(dt, lat, lon))

    return rmc_pts, ecef_pts


def same_second_pairs(rmc: list[Point], ecef: list[Point]) -> list[float]:
    rmc_map = {(p.t.hour, p.t.minute, p.t.second): p for p in rmc}
    out: list[float] = []
    for e in ecef:
        key = (e.t.hour, e.t.minute, e.t.second)
        if key in rmc_map:
            r = rmc_map[key]
            out.append(haversine_m(e.lat, e.lon, r.lat, r.lon))
    return out


def replay_fusion(log_path: Path, m: Metrics) -> None:
    nav = _load_navigation_config(
        {
            "Navigation": {
                "Profile": "tram",
                "VehicleProfilesPath": "VehicleProfiles.toml",
                "OutputRateHz": 10,
                "SerialRestartOnRmcLoss": "no",
                "SerialRestartAfterSec": 90,
            }
        },
        ROOT / "etc",
    )
    fusion = NavFusion(nav.profile)
    clock = SimClock()
    last_rmc_dt: datetime | None = None
    last_fusion: Point | None = None
    last_mono: float | None = None
    was_lost = False

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        out = None
        with patch_monotonic(clock):
            if GNRMC_RE.match(s):
                rec = parse_rmc(s, None)
                if not rec or not rec.get("datetime"):
                    continue
                dt = datetime.fromisoformat(rec["datetime"])
                last_rmc_dt = dt
                clock.advance_to(dt)
                out = fusion.ingest_rmc(rec)
            elif ECEFPOSVEL_RE.match(s) and last_rmc_dt is not None:
                rec = parse_ecefposvel(s)
                if not rec:
                    continue
                dt = _ecef_time_with_rmc_date(s, last_rmc_dt)
                if dt is None:
                    continue
                clock.advance_to(dt)
                out = fusion.ingest_ecef(rec)

        if out is None:
            continue
        if was_lost and out.quality != "LOST":
            was_lost = False
        if out.quality == "LOST":
            if not was_lost:
                m.fusion_lost_segments += 1
                was_lost = True
            continue

        m.quality_counts[out.quality] += 1
        m.fusion_n += 1
        lat, lon = signed_lat_lon(out.latitude, out.latitude_hemi, out.longitude, out.longitude_hemi)
        fp = Point(datetime.fromisoformat(out.datetime_iso) if out.datetime_iso else last_rmc_dt or datetime.now(timezone.utc), lat, lon, out.speed)
        mono = clock.monotonic()
        if last_fusion and last_mono:
            dt_s = mono - last_mono
            if dt_s > 0:
                d = haversine_m(last_fusion.lat, last_fusion.lon, fp.lat, fp.lon)
                m.fusion_adj_m.append(d)
                m.fusion_adj_spd.append((d / dt_s) * 3.6)
                m.fusion_intervals.append(dt_s)
        if out.quality == "GOOD" and last_rmc_dt:
            rlat, rlon = lat, lon  # fusion == RMC on GOOD
            m.fusion_rmc_m.append(0.0 if out.quality == "GOOD" else 0.0)
        last_fusion, last_mono = fp, mono


class patch_monotonic:
    def __init__(self, clock: SimClock) -> None:
        self.clock = clock

    def __enter__(self):
        self._orig = _time.monotonic
        _time.monotonic = self.clock.monotonic
        return self

    def __exit__(self, *_) -> None:
        _time.monotonic = self._orig


def fusion_vs_rmc_on_good(log_path: Path) -> list[float]:
    """Distance fusion output vs RMC when quality=GOOD."""
    nav = _load_navigation_config(
        {"Navigation": {"Profile": "tram", "VehicleProfilesPath": "VehicleProfiles.toml", "OutputRateHz": 10, "SerialRestartOnRmcLoss": "no", "SerialRestartAfterSec": 90}},
        ROOT / "etc",
    )
    fusion = NavFusion(nav.profile)
    clock = SimClock()
    last_rmc_dt: datetime | None = None
    dists: list[float] = []

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        with patch_monotonic(clock):
            if GNRMC_RE.match(s):
                rec = parse_rmc(s, None)
                if not rec or not rec.get("datetime"):
                    continue
                dt = datetime.fromisoformat(rec["datetime"])
                last_rmc_dt = dt
                clock.advance_to(dt)
                rlat, rlon = signed_lat_lon(rec["latitude"], rec["latitude_hemi"], rec["longitude"], rec["longitude_hemi"])
                out = fusion.ingest_rmc(rec)
                if out and out.quality == "GOOD":
                    flat, flon = signed_lat_lon(out.latitude, out.latitude_hemi, out.longitude, out.longitude_hemi)
                    dists.append(haversine_m(flat, flon, rlat, rlon))
            elif ECEFPOSVEL_RE.match(s) and last_rmc_dt:
                rec = parse_ecefposvel(s)
                if not rec:
                    continue
                dt = _ecef_time_with_rmc_date(s, last_rmc_dt)
                if dt is None:
                    continue
                clock.advance_to(dt)
                fusion.ingest_ecef(rec)
    return dists


def main() -> None:
    print(f"Analyzing {LOG_PATH} ({LOG_PATH.stat().st_size // 1024} KiB)\n")
    rmc, ecef = parse_log(LOG_PATH)
    m = Metrics()
    m.rmc_n, m.ecef_n = len(rmc), len(ecef)

    for i in range(1, len(rmc)):
        dt = (rmc[i].t - rmc[i - 1].t).total_seconds()
        m.rmc_intervals.append(dt)
        m.rmc_gaps.append(dt)
    for i in range(1, len(ecef)):
        m.ecef_intervals.append((ecef[i].t - ecef[i - 1].t).total_seconds())

    _adj(rmc, m.rmc_adj_m, m.rmc_adj_spd, m.rmc_field_delta_spd)
    _adj(ecef, m.ecef_adj_m, m.ecef_adj_spd)
    m.rmc_ecef_same_sec_m = same_second_pairs(rmc, ecef)

    # ECEF during RMC gaps >1s (no RMC same second)
    rmc_sec = {(p.t.hour, p.t.minute, p.t.second) for p in rmc}
    ecef_only_gap: list[float] = []
    for i in range(1, len(ecef)):
        if (ecef[i].t.hour, ecef[i].t.minute, ecef[i].t.second) in rmc_sec:
            continue
        dt = (ecef[i].t - ecef[i - 1].t).total_seconds()
        if dt <= 0 or dt > 15:
            continue
        ecef_only_gap.append(haversine_m(ecef[i - 1].lat, ecef[i - 1].lon, ecef[i].lat, ecef[i].lon))

    replay_fusion(LOG_PATH, m)
    fusion_good_dist = fusion_vs_rmc_on_good(LOG_PATH)

    # short gap ecef when dt<=10s between ecef points without rmc same sec
    ecef_short_gap_adj: list[float] = []
    for i in range(1, len(ecef)):
        key = (ecef[i].t.hour, ecef[i].t.minute, ecef[i].t.second)
        if key in rmc_sec:
            continue
        dt = (ecef[i].t - ecef[i - 1].t).total_seconds()
        if 0 < dt <= 10:
            ecef_short_gap_adj.append(haversine_m(ecef[i - 1].lat, ecef[i - 1].lon, ecef[i].lat, ecef[i].lon))

    duration_h = (rmc[-1].t - rmc[0].t).total_seconds() / 3600 if len(rmc) > 1 else 0
    rmc_cov = len({(p.t.hour, p.t.minute, p.t.second) for p in rmc})
    ecef_sec = len({(p.t.hour, p.t.minute, p.t.second) for p in ecef})
    common_sec = len(set((p.t.hour, p.t.minute, p.t.second) for p in rmc) & set((p.t.hour, p.t.minute, p.t.second) for p in ecef))

    print("=== CONTEXT ===")
    print(f"Duration (RMC span): {duration_h:.2f} h | RMC points: {m.rmc_n} | ECEF valid: {m.ecef_n}")
    print(f"Unique seconds RMC: {rmc_cov} | ECEF: {ecef_sec} | both: {common_sec} ({100*common_sec/max(ecef_sec,1):.1f}% ECEF sec with RMC)")
    print(f"RMC gaps >10s: {sum(1 for g in m.rmc_gaps if g>10)} | max gap: {max(m.rmc_gaps) if m.rmc_gaps else 0:.0f}s")
    print(f"Fusion publishes: {m.fusion_n} | LOST segments: {m.fusion_lost_segments} | quality: {dict(m.quality_counts)}")

    rows = [
        ("Δt between RMC (s)", stats(m.rmc_intervals)),
        ("Δt between ECEF (s)", stats(m.ecef_intervals)),
        ("Δt between Fusion publishes (s)", stats(m.fusion_intervals)),
        ("RMC↔ECEF same second (m)", stats(m.rmc_ecef_same_sec_m)),
        ("Fusion↔RMC on GOOD (m)", stats(fusion_good_dist)),
        ("Adjacent Δpos RMC (m)", stats(m.rmc_adj_m)),
        ("Adjacent Δpos ECEF all (m)", stats(m.ecef_adj_m)),
        ("Adjacent Δpos ECEF no-RMC sec, Δt≤10s (m)", stats(ecef_short_gap_adj)),
        ("Adjacent Δpos Fusion (m)", stats(m.fusion_adj_m)),
        ("Speed from Δpos RMC (km/h)", stats(m.rmc_adj_spd)),
        ("Speed from Δpos ECEF all (km/h)", stats(m.ecef_adj_spd)),
        ("Speed from Δpos ECEF gap≤10s (km/h)", stats([(d/1.0)*3.6 for d in ecef_short_gap_adj])),
        ("Speed from Δpos Fusion (km/h)", stats(m.fusion_adj_spd)),
        ("|RMC speed field − Δpos| (km/h)", stats(m.rmc_field_delta_spd)),
    ]

    print("\n=== METRICS TABLE ===")
    print(f"{'Metric':<42} {'n':>7} {'mean':>9} {'median':>9} {'p95':>9} {'max':>10}")
    print("-" * 88)
    for name, st in rows:
        print(f"{name:<42} {st['n']:7.0f} {st['mean']:9.3f} {st['median']:9.3f} {st['p95']:9.3f} {st['max']:10.3f}")


if __name__ == "__main__":
    main()
