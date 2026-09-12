"""Service shutdown hooks release partial registrations and preserve failures."""

import asyncio
import signal
from unittest.mock import Mock

import pytest
from polybot.framework.lifecycle import install_signal_handlers


def test_shutdown_hooks_set_event_and_remove_only_installed_handlers(monkeypatch):
    loop = Mock()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    shutdown = asyncio.Event()
    remove = install_signal_handlers(shutdown)
    signum, callback = loop.add_signal_handler.call_args_list[0].args
    assert signum == signal.SIGINT
    callback()
    assert shutdown.is_set()
    remove()
    assert [call.args[0] for call in loop.remove_signal_handler.call_args_list] == [
        signal.SIGINT,
        signal.SIGTERM,
    ]


@pytest.mark.parametrize("failure", [NotImplementedError, RuntimeError])
@pytest.mark.parametrize("required", [False, True])
def test_partial_hook_installation_cleans_up_and_respects_host_policy(
    monkeypatch, failure, required
):
    loop = Mock()
    loop.add_signal_handler.side_effect = [None, failure("unsupported")]
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    if required:
        with pytest.raises(failure, match="unsupported"):
            install_signal_handlers(asyncio.Event())
    else:
        remove = install_signal_handlers(asyncio.Event(), required=False)
        loop.remove_signal_handler.assert_not_called()
        remove()
    loop.remove_signal_handler.assert_called_once_with(signal.SIGINT)
