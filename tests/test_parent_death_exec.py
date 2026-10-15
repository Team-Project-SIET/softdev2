"""Controlled Linux supervisor death, without launching OpenTTD."""

import ctypes
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death contract")
def test_one_shot_exec_child_dies_when_supervisor_is_sigkilled() -> None:
    shim = Path(__file__).parents[1] / "app/simulation/openttd/parent_death_exec.py"
    supervisor_code = (
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, sys.argv[1], str(os.getpid()), "
        "sys.executable, '-c', 'import time; time.sleep(60)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code, str(shim)],
        stdout=subprocess.PIPE,
        text=True,
    )
    child_pid = None
    pidfd = None
    try:
        assert supervisor.stdout is not None
        assert select.select([supervisor.stdout], [], [], 5)[0]
        child_pid = int(supervisor.stdout.readline())
        pidfd = ctypes.CDLL(None).syscall(434, child_pid, 0)  # Linux pidfd_open.
        assert pidfd >= 0
        assert os.getpgid(child_pid) == child_pid
        supervisor.kill()
        supervisor.wait(timeout=5)
        assert select.select([pidfd], [], [], 5)[0], "owned child survived supervisor death"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=5)
        if pidfd is not None:
            if not select.select([pidfd], [], [], 0)[0] and child_pid is not None:
                ctypes.CDLL(None).syscall(424, pidfd, signal.SIGKILL, 0, 0)
                assert select.select([pidfd], [], [], 5)[0]
            os.close(pidfd)
        if supervisor.stdout is not None:
            supervisor.stdout.close()
