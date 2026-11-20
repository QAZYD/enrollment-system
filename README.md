# Distributed Enrollment System

```
enrollment/
├── protos/              shared contract: enrollment.proto (+ generated pb2 files)
├── common/              shared: config.py, jwt_util.py, seed_data.py
├── services/
│   ├── auth/            Person 1: server.py, test_auth.py   (port 50051)
│   ├── course/          Person 2: server.py, test_course.py (port 50052)
│   └── grade/           Person 3: server.py, test_grade.py  (port 50053)
├── view/                Person 4: app.py, templates/        (port 5000)
├── tools/               mock_server.py, run_all.py, check_nodes.py
├── gen_protos.py
└── requirements.txt
```

## Setup (everyone)
```
pip install -r requirements.txt
python gen_protos.py        # creates protos/enrollment_pb2.py + protos/enrollment_pb2_grpc.py
```
**Run everything from the project root using `python -m`**, so imports work:

| What | Command |
|---|---|
| Auth node | `python -m services.auth.server` |
| Course node | `python -m services.course.server` |
| Grade node | `python -m services.grade.server` |
| View node | `python -m view.app` |
| All nodes in one terminal | `python -m tools.run_all` (`--skip grade` for the node-down demo) |
| Mock of all services | `python -m tools.mock_server` (`--down grade` to fake an outage) |
| Which nodes are up | `python -m tools.check_nodes` |

Imports inside any file:
```python
from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data
```

## Shared contract: don't change these without telling the team
- `protos/enrollment.proto`: only ADD fields, never rename or remove them. Re-run `gen_protos.py` after pulling changes.
- `common/jwt_util.py`: `make(user, role)`, `verify(token)`, `claims_or_none(token)`
- `common/config.py`: ports and addresses (override with env vars on VMs)
- `common/seed_data.py`: users, courses, enrollments, grades. All passwords are `password`.

## Developing without the other nodes
- **View (Person 4):** run `python -m tools.mock_server` and build against it.
- **Services (Persons 1–3):** write a test client in your own folder. You don't need the auth node to get a token:
  ```python
  import grpc
  from protos import enrollment_pb2 as pb, enrollment_pb2_grpc as rpc
  from common import jwt_util, config
  tok = jwt_util.make("student1", "student")
  stub = rpc.CourseServiceStub(grpc.insecure_channel(config.COURSE_ADDR))
  print(stub.ListCourses(pb.Token(jwt=tok), timeout=2))
  ```
  Stop the mock before running your real service, because they use the same ports.

## Rules every service follows
- Check the token first: `claims = jwt_util.claims_or_none(req.jwt)`. If it's `None`, return `ok=False`.
- Check the role for protected actions (enroll → student, upload grade → faculty).
- Report failures with `ok=False, msg=...` and don't raise. Network errors are the only thing the view treats as "service down".
- Services **never call each other**. Each keeps its own SQLite db in its own folder.
- Bind to `0.0.0.0:<PORT>` from `common/config.py`.
