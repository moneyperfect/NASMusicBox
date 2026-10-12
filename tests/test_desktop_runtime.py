import os
import sys
import threading

import pytest

from desktop_runtime import DesktopInstance, configure_windowed_logs


@pytest.mark.skipif(os.name != "nt", reason="Windows named handles")
def test_second_launch_activates_first_and_handles_release(tmp_path):
    first, second = DesktopInstance(tmp_path), DesktopInstance(tmp_path)
    activated = threading.Event()
    try:
        assert first.acquire()
        first.listen(activated.set)
        assert not second.acquire()
        assert activated.wait(3)
    finally:
        second.close()
        first.close()
    third = DesktopInstance(tmp_path)
    try:
        assert third.acquire()
    finally:
        third.close()


def test_windowed_backend_has_writable_log_streams(monkeypatch, tmp_path):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        path = configure_windowed_logs(tmp_path, backend=True)
        stream = sys.stderr
        stream.write("backend startup diagnostic\n")
        stream.flush()
        assert path.read_text(encoding="utf-8").endswith("backend startup diagnostic\n")
    stream.close()
