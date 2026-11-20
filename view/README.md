# View Node (Person 4 — Flask MVC)

Stateless Flask MVC frontend bound to `0.0.0.0:config.VIEW_PORT` (default `5000`). All data comes from the Auth, Course, and Grade gRPC nodes.

## Setup (Run from Project Root)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gen_protos.py   # creates protos/enrollment_pb2.py + protos/enrollment_pb2_grpc.py
```

## Running Locally Against the Mock Server

Terminal 1 (mock backends on ports `50051`–`50053`):

```powershell
.\.venv\Scripts\python.exe -m tools.mock_server
```

Terminal 2 (view node on `http://localhost:5000`):

```powershell
.\.venv\Scripts\python.exe -m view.app
```

Check which nodes are up from a third terminal:

```powershell
.\.venv\Scripts\python.exe -m tools.check_nodes
```

Or run real nodes together (including Person 1's `python -m services.auth.server`):

```powershell
.\.venv\Scripts\python.exe -m tools.run_all
```

Seed accounts (`common/seed_data.py`, password `password`): `student1`, `student2`, `student3` (`student`), `faculty1` (`faculty`).

Stop `tools.mock_server` (`Ctrl+C`) before running real services because they use the same ports.

## Automated Tests

```powershell
.\.venv\Scripts\python.exe -m unittest view.test_view -v
```

## Configuration (Environment Variables)

- `AUTH_ADDR`, `COURSE_ADDR`, `GRADE_ADDR`: gRPC backend addresses (default `localhost:50051`, `localhost:50052`, `localhost:50053`, read via `common/config.py`). Set these on the View VM when running across separate machines.
- `VIEW_PORT`: HTTP bind port for Flask (default `5000`, read via `common/config.py`).
- `RPC_TIMEOUT`: Per-RPC gRPC deadline in seconds (default `2`, read via `common/config.py`).
- `JWT_SECRET`: Shared HMAC secret read by `common/jwt_util.py` (default `dev-secret-change-me`). Must match Auth, Course, and Grade nodes on all VMs.
- `FLASK_SECRET_KEY`: Secret used by Flask to sign its stateless session cookie (flash messages and CSRF tokens; default `dev-flask-secret-change-me`). Set a strong shared random value for production/VM demos.
- `COOKIE_SECURE`: Set to `1` when serving over HTTPS; keep `0` (default) for plain-HTTP localhost or LAN/VM demos so browsers retain the JWT cookie.

## Fault-Tolerance Demonstration Sequence

Note: Restarting `tools.mock_server` resets its in-memory enrollments and grades. For persistent state across individual service restarts, coordinate independent real-service testing with Person 1 using `python -m services.auth.server` or `python -m tools.run_all --skip <node>`.

1. Start all services (`python -m tools.mock_server`) and `python -m view.app`. Sign in as `student1` (`password`).
2. **Grade node down:** Restart mock with `python -m tools.mock_server --down grade`. Refresh `/grades` → shows **Grade service unavailable**. Navigate to `/courses` and enroll → continues working.
3. **Course node down:** Restart mock with `python -m tools.mock_server --down course`. Refresh `/courses` → shows **Course service unavailable**. Navigate to `/grades` (or `/grades/upload` as `faculty1`) → continues working.
4. **Auth node down:** While already signed in, restart mock with `python -m tools.mock_server --down auth`. Browse `/courses` and `/grades`, then click **Sign out** → existing valid cookie keeps working and logout succeeds locally. Try signing in again → `/login` shows **Auth service unavailable**.
5. **Recovery:** Restart mock with `python -m tools.mock_server` (no flags) and retry `/login` without restarting `view.app` → view reconnects cleanly.
