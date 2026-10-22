"""Metric catalog and deterministic series generator.

METRIC_CATALOG is the single source of truth for metric names. Phase 3 builds the
query_metric tool description from it and Phase 6 uses it as the Prometheus allowlist.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TypedDict

from rootsignal_agent.sim.models import MetricSpec

LOOKBACK_HOURS = 6
RESOLUTION_MINUTES = 5


class MetricInfo(TypedDict):
    unit: str
    baseline: float  # healthy value
    description: str


METRIC_CATALOG: dict[str, MetricInfo] = {
    "executor_memory_utilization": {
        "unit": "ratio",
        "baseline": 0.55,
        "description": "Fraction of executor heap memory in use (1.0 = full).",
    },
    "gc_time_ratio": {
        "unit": "ratio",
        "baseline": 0.03,
        "description": "Fraction of executor time spent in garbage collection.",
    },
    "task_duration_median_seconds": {
        "unit": "seconds",
        "baseline": 12.0,
        "description": "Median duration of tasks in the job's current stage.",
    },
    "task_duration_max_seconds": {
        "unit": "seconds",
        "baseline": 30.0,
        "description": "Duration of the slowest task in the job's current stage.",
    },
    "input_rows_total": {
        "unit": "rows",
        "baseline": 2_400_000.0,
        "description": "Rows read by the job from its input tables.",
    },
    "cluster_cpu_utilization": {
        "unit": "ratio",
        "baseline": 0.45,
        "description": "Fraction of cluster CPU capacity in use.",
    },
    "pending_containers": {
        "unit": "containers",
        "baseline": 0.0,
        "description": "Containers requested by jobs but not yet scheduled.",
    },
    "disk_utilization_ratio": {
        "unit": "ratio",
        "baseline": 0.40,
        "description": "Fraction of local scratch disk used on the job's workers.",
    },
    "network_error_rate": {
        "unit": "ratio",
        "baseline": 0.002,
        "description": "Fraction of outbound requests that time out or fail.",
    },
    "job_retry_count": {
        "unit": "retries",
        "baseline": 0.0,
        "description": "Task and job retries in the window.",
    },
}


def _window_start(as_of: datetime) -> datetime:
    return as_of - timedelta(hours=LOOKBACK_HOURS)


def _value_at(spec: MetricSpec, minute: int) -> float:
    """Noise-free value of the series `minute` minutes after the window start."""
    if spec.shape == "flat":
        return spec.baseline
    assert spec.peak is not None and spec.start_minute is not None  # checked by the model
    if spec.shape == "step":
        return spec.peak if minute >= spec.start_minute else spec.baseline
    assert spec.end_minute is not None
    if spec.shape == "spike":
        in_spike = spec.start_minute <= minute < spec.end_minute
        return spec.peak if in_spike else spec.baseline
    # ramp: baseline until start, linear up to peak at end, then stays at peak
    if minute <= spec.start_minute:
        return spec.baseline
    if minute >= spec.end_minute:
        return spec.peak
    frac = (minute - spec.start_minute) / (spec.end_minute - spec.start_minute)
    return spec.baseline + frac * (spec.peak - spec.baseline)


def generate_series(spec: MetricSpec, as_of: datetime) -> list[tuple[datetime, float]]:
    """Deterministic series covering the lookback window, ending exactly at as_of."""
    rng = random.Random(spec.seed)  # local RNG: never touch the global one
    start = _window_start(as_of)
    n_points = LOOKBACK_HOURS * 60 // RESOLUTION_MINUTES + 1
    points: list[tuple[datetime, float]] = []
    for i in range(n_points):
        minute = i * RESOLUTION_MINUTES
        value = _value_at(spec, minute)
        value *= 1 + rng.uniform(-spec.noise, spec.noise)  # one draw per point, always
        points.append((start + timedelta(minutes=minute), max(value, 0.0)))
    return points


def build_all_series(
    specs: list[MetricSpec], as_of: datetime
) -> dict[str, list[tuple[datetime, float]]]:
    """Series for EVERY catalog metric. Unspecified ones are healthy and flat, so the
    set of metrics that exist never hints at the root cause."""
    by_name = {s.name: s for s in specs}
    series: dict[str, list[tuple[datetime, float]]] = {}
    for name, info in METRIC_CATALOG.items():
        spec = by_name.get(name)
        if spec is None:
            # Seed from the name so the fill is stable across runs and scenarios.
            seed = sum(ord(c) * (i + 1) for i, c in enumerate(name))
            spec = MetricSpec(name=name, shape="flat", baseline=info["baseline"], seed=seed)
        series[name] = generate_series(spec, as_of)
    return series
