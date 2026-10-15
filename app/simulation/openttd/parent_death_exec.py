"""Linux-only one-shot exec shim for an owned dedicated OpenTTD child.

PR_SET_PDEATHSIG follows the child across ordinary exec. The parent-PID checks
close the race where the Python supervisor exits before the signal is armed.
This file does not remain as a separate process after os.execv().
"""

import ctypes
import os
import signal
import sys


def main() -> None:
    if len(sys.argv) < 4:
        os._exit(125)
    expected_parent = int(sys.argv[1])
    if os.getppid() != expected_parent:
        os._exit(125)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        os._exit(125)
    if os.getppid() != expected_parent:
        os._exit(125)
    executable = sys.argv[2]
    os.execv(executable, [executable, *sys.argv[3:]])


if __name__ == "__main__":
    main()
