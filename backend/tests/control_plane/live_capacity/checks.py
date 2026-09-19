"""Executable gates for evidence this runner can measure directly."""


def evaluate(measurements, reports, workload, exit_codes, browser_exit_code):
    counts = measurements.counts
    expected_viewers = (
        round(workload.producers * workload.watched_percent / 100)
        * workload.viewers_per_watched_run
        + workload.hot_run_viewers
    )
    watched = expected_viewers > 0
    age = sorted(measurements.samples.get("snapshot_age_seconds", ()))
    initial = measurements.samples.get("initial_live_seconds", ())
    process_counts = [report.get("counts", {}) for report in reports]
    workers = [report for report in reports if report["role"] == "worker"]
    checks = {
        "processes_completed": all(code == 0 for code in exit_codes)
        and len(reports) == len(exit_codes),
        "snapshot_ordering": counts.get("identity_regressions", 0) == 0,
        "durable_ordering": counts.get("cursor_regressions", 0) == 0,
        "watched_delivery": counts.get("viewers_with_live", 0) == expected_viewers,
        "terminal_delivery": counts.get("viewers_with_terminal", 0) == expected_viewers
        if workload.mode == "integrated"
        else None,
        "owned_stop": sum(
            report.get("counts", {}).get("owned_stops", 0) for report in workers
        )
        == workload.producers
        if workload.mode == "integrated"
        else None,
        "owned_heartbeat": all(
            report.get("counts", {}).get("owned_heartbeats", 0) > 0
            for report in workers
        )
        if workload.mode == "integrated"
        else None,
        "browser_merge": browser_exit_code == 0 if watched else True,
        "zero_live_and_health_sql": bool(workers)
        and all(
            report["counts"].get(phase + suffix) == 0
            for report in workers
            for phase in ("live_publish", "health_write")
            for suffix in ("_sql_queries", "_sql_checkouts")
        ),
        "publisher_bounds": all(
            count.get("publisher_bound_violations", 0) == 0 for count in process_counts
        ),
        "subscription_bounds": all(
            count.get("subscription_bound_violations", 0) == 0
            for count in process_counts
        ),
        "no_worker_chart_history": all(
            count.get("retained_history_violations", 0) == 0 for count in process_counts
        ),
        "snapshot_age_p95": bool(age)
        and age[min(len(age) - 1, int(len(age) * 0.95))] <= 0.5
        if watched
        else True,
        "snapshot_age_p99": bool(age)
        and age[min(len(age) - 1, int(len(age) * 0.99))] <= 1
        if watched
        else True,
        "initial_live_state": (
            bool(initial) and max(initial) <= 2.5 if watched else True
        )
        if not workload.faults
        else None,
        "no_viewer_health": all(
            report.get("telemetry", {}).get("health_written", 0) > 0
            for report in workers
        )
        if not watched
        else True,
        "no_viewer_snapshot_bytes": all(
            report.get("telemetry", {}).get("published_bytes", 0) == 0
            for report in workers
        )
        if not watched
        else None,
        "slow_client_closed": any(
            report.get("telemetry", {}).get("slow_client", 0) > 0 for report in reports
        )
        if workload.slow_viewers
        else None,
        "thirty_minute_duration": workload.duration_seconds >= 1800,
        "four_hour_soak": True if workload.duration_seconds >= 4 * 3600 else None,
        "cpu_and_network_headroom": None,
        "stable_memory_over_soak": None,
        "deployment_proxy": None,
        "browser_rendering_at_target_scale": None,
    }
    required = [
        value
        for name, value in checks.items()
        if value is not None
        and (
            not workload.smoke
            or name not in {"thirty_minute_duration", "four_hour_soak"}
        )
    ]
    return checks, all(required)
