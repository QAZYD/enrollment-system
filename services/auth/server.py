"""AUTH NODE (Person 1) - gRPC AuthService on AUTH_PORT (default 50051).

Owns its own SQLite db (services/auth/auth.db), seeded from common/seed_data.USERS on first run.
Login checks username/password and returns a signed JWT (common/jwt_util).
Other nodes verify that JWT locally, so they keep working even if this node is down.

    python -m services.auth.server
"""
import hashlib
import os
import sqlite3
import threading
from concurrent import futures

import grpc

from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.db")
_db_lock = threading.Lock()


def hash_pw(password: str) -> str:
    # Minimal on purpose (class project). Production would use bcrypt/argon2 with salts.
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('student', 'faculty')))""")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO users VALUES (?, ?, ?)",
                [(u, hash_pw(info["password"]), info["role"]) for u, info in seed_data.USERS.items()],
            )
            print(f"[auth] seeded {len(seed_data.USERS)} users into auth.db")


class AuthService(rpc.AuthServiceServicer):
    def Login(self, request, context):
        username = request.username.strip()
        if not username or not request.password:
            return pb.LoginReply(ok=False, msg="Username and password are required")

        with _db_lock, sqlite3.connect(DB_PATH) as db:
            row = db.execute(
                "SELECT password_hash, role FROM users WHERE username = ?", (username,)
            ).fetchone()

        if row is None or row[0] != hash_pw(request.password):
            print(f"[auth] failed login: {username!r}")
            return pb.LoginReply(ok=False, msg="Invalid username or password")

        role = row[1]
        token = jwt_util.make(username, role)
        print(f"[auth] login ok: {username} ({role})")
        return pb.LoginReply(ok=True, jwt=token, role=role, msg="Logged in")


def serve():
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    rpc.add_AuthServiceServicer_to_server(AuthService(), server)
    server.add_insecure_port(f"0.0.0.0:{config.AUTH_PORT}")
    server.start()
    print(f"[auth] AuthService listening on 0.0.0.0:{config.AUTH_PORT}  (Ctrl+C to stop)")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("[auth] shutting down")
        server.stop(0)


if __name__ == "__main__":
    serve()
