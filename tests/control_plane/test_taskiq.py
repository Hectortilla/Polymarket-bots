"""Taskiq broker configuration contract."""

from polybot_control_plane.execution.taskiq_app import broker


def test_new_worker_group_reads_already_queued_tasks() -> None:
    assert broker.consumer_id == "0-0"
