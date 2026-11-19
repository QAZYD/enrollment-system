# Distributed Enrollment System

| Node | Owner | File | Port |
|---|---|---|---|
| Auth | Person 1 | `auth_service.py` | 50051 |
| Course | Person 2 | `course_service.py` | 50052 |
| Grade | Person 3 | `grade_service.py` | 50053 |
| View (Flask MVC) | Person 4 | `view/app.py` | 5000 |

## Setup (everyone)
```
pip install -r requirements.txt
python gen_protos.py        # creates enrollment_pb2.py + enrollment_pb2_grpc.py
```
Run every script **from the project root** (e.g. `python -m view.app`), so `common/` and the generated files can be imported.

## Shared contract (Step 0): don't change these without telling the team
- `protos/enrollment.proto`: only ADD fields, never rename or remove them. Re-run `gen_protos.py` after pulling changes.
- `common/jwt_util.py`: `make(user, role)`, `verify(token)`, `claims_or_none(token)`
- `common/config.py`: ports and addresses (override with env vars on VMs)
- `common/seed_data.py`: users, courses, enrollments, grades. All passwords are `password`.

## Developing without the other nodes
- **View (Person 4):** run `python mock_server.py`, then build against it. Use `python mock_server.py --down grade` to test "service unavailable" pages.
- **Services (Persons 1–3):** write a small test client. You don't need the auth node to get a token:
  ```python
  import grpc, enrollment_pb2 as pb, enrollment_pb2_grpc as rpc
  from common import jwt_util, config
  tok = jwt_util.make("student1", "student")
  stub = rpc.CourseServiceStub(grpc.insecure_channel(config.COURSE_ADDR))
  print(stub.ListCourses(pb.Token(jwt=tok), timeout=2))
  ```
  (The mock uses the same ports, so stop it before running your real service.)

## Rules every service follows
- Check the token first: `claims = jwt_util.claims_or_none(req.jwt)`. If it's `None`, return `ok=False`.
- Check the role for protected actions (enroll → student, upload grade → faculty).
- Report failures with `ok=False, msg=...` and don't raise. Network errors are the only thing the view treats as "service down".
- Services **never call each other**. Each one has its own SQLite db.
- Bind to `0.0.0.0:<PORT>` from `common/config.py`.

## Generated files
`enrollment_pb2*.py` are generated. Either everyone runs `gen_protos.py`, or commit them, but pick one approach.
