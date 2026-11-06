import subprocess
import sys
import textwrap
import time
from pathlib import Path

import config

ROOT = config.resource_path().parent
SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {root!r})
    from PySide6.QtCore import QCoreApplication
    from ui import single_instance
    app = QCoreApplication([])
    lock = single_instance.acquire(sys.argv[1])
    print("locked" if lock else "refused", flush=True)
    if lock and len(sys.argv) > 2:
        time.sleep(float(sys.argv[2]))
""").format(root=str(ROOT))


def start(path, hold=None):
    args = [sys.executable, "-c", SCRIPT, str(path)] + ([str(hold)] if hold else [])
    return subprocess.Popen(args, stdout=subprocess.PIPE, text=True)


def first_line(proc):
    return proc.stdout.readline().strip()


def test_second_copy_is_refused_and_lock_frees_when_the_first_exits(tmp_path):
    lock_file = tmp_path / "x.lock"
    first = start(lock_file, hold=4)
    assert first_line(first) == "locked"
    second = start(lock_file)
    assert first_line(second) == "refused"
    first.wait(timeout=20)
    third = start(lock_file)
    assert first_line(third) == "locked"
    for p in (second, third):
        p.wait(timeout=20)


def test_a_crashed_copy_does_not_block_the_next_start(tmp_path):
    lock_file = tmp_path / "x.lock"
    crashed = start(lock_file, hold=60)
    assert first_line(crashed) == "locked"
    crashed.kill()  # like a power cut or "End task": no chance to clean up
    crashed.wait(timeout=20)
    time.sleep(0.3)
    nxt = start(lock_file)
    assert first_line(nxt) == "locked"
    nxt.wait(timeout=20)
