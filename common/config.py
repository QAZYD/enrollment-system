"""Ports and addresses for every node.

Servers bind to 0.0.0.0:<PORT>. Clients connect to <ADDR>.
On one laptop the defaults just work. On VMs, set env vars on the VIEW machine, e.g.
    AUTH_ADDR=192.168.1.11:50051  COURSE_ADDR=192.168.1.12:50052  GRADE_ADDR=192.168.1.13:50053
"""
import os

AUTH_PORT = int(os.getenv("AUTH_PORT", "50051"))
COURSE_PORT = int(os.getenv("COURSE_PORT", "50052"))
GRADE_PORT = int(os.getenv("GRADE_PORT", "50053"))
VIEW_PORT = int(os.getenv("VIEW_PORT", "5000"))

AUTH_ADDR = os.getenv("AUTH_ADDR", f"localhost:{AUTH_PORT}")
COURSE_ADDR = os.getenv("COURSE_ADDR", f"localhost:{COURSE_PORT}")
GRADE_ADDR = os.getenv("GRADE_ADDR", f"localhost:{GRADE_PORT}")

RPC_TIMEOUT = float(os.getenv("RPC_TIMEOUT", "2"))  # seconds; view uses this on every call
