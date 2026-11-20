"""Show which nodes are UP or DOWN (uses the addresses in common/config.py / env vars).

    python -m tools.check_nodes

Handy during integration and for the fault-tolerance demo.
"""
import urllib.request

import grpc

from common import config

GRPC_NODES = {"auth": config.AUTH_ADDR, "course": config.COURSE_ADDR, "grade": config.GRADE_ADDR}
VIEW_URL = f"http://localhost:{config.VIEW_PORT}/"


def grpc_up(addr):
    ch = grpc.insecure_channel(addr)
    try:
        grpc.channel_ready_future(ch).result(timeout=1.5)
        return True
    except grpc.FutureTimeoutError:
        return False
    finally:
        ch.close()


def http_up(url):
    try:
        urllib.request.urlopen(url, timeout=1.5)
        return True
    except urllib.error.HTTPError:
        return True  # server answered (even 4xx/5xx means it's up)
    except Exception:
        return False


if __name__ == "__main__":
    for name, addr in GRPC_NODES.items():
        print(f"  {name:<6} {addr:<22} {'UP' if grpc_up(addr) else 'DOWN'}")
    print(f"  {'view':<6} {VIEW_URL:<22} {'UP' if http_up(VIEW_URL) else 'DOWN'}")
