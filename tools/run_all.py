"""Start every node on THIS machine in one terminal (for local integration).
Run from the project root:

    python -m tools.run_all                      # start every node whose file exists
    python -m tools.run_all --only auth course   # start just these
    python -m tools.run_all --skip grade         # everything except grade (node-down demo)

Each line of output is prefixed with the node name. Ctrl+C stops them all.
Nodes whose file doesn't exist yet are skipped with a note, so this works mid-project.
On separate VMs, don't use this: run each node's own command on its own machine.
"""
import argparse
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root

# name -> (file that must exist, module to run with "python -m")
NODES = {
    "auth":   (os.path.join("services", "auth", "server.py"),   "services.auth.server"),
    "course": (os.path.join("services", "course", "server.py"), "services.course.server"),
    "grade":  (os.path.join("services", "grade", "server.py"),  "services.grade.server"),
    "view":   (os.path.join("view", "app.py"),                   "view.app"),
}


def pump(name, proc):
    for line in proc.stdout:
        print(f"[{name:<6}] {line.rstrip()}", flush=True)
    print(f"[{name:<6}] *** exited with code {proc.wait()} ***", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=list(NODES))
    ap.add_argument("--skip", nargs="*", default=[], choices=list(NODES))
    args = ap.parse_args()

    wanted = [n for n in (args.only or NODES) if n not in args.skip]
    procs = []
    for name in wanted:
        must_exist, module = NODES[name]
        if not os.path.exists(os.path.join(ROOT, must_exist)):
            print(f"[{name:<6}] skipped ({must_exist} not found yet)")
            continue
        p = subprocess.Popen(
            [sys.executable, "-u", "-m", module],  # sys.executable = the venv's python
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        procs.append((name, p))
        threading.Thread(target=pump, args=(name, p), daemon=True).start()
        print(f"[{name:<6}] started (pid {p.pid})")

    if not procs:
        print("Nothing to run.")
        return
    print("All requested nodes started. Ctrl+C to stop all.\n")
    try:
        while any(p.poll() is None for _, p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping all nodes...")
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
