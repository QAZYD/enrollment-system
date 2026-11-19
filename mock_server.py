"""Fake Auth/Course/Grade services for developing the view without the real nodes.

Runs each fake service on its REAL port (from common/config.py), so the view
needs no changes when switching to the real services.

    python mock_server.py                 # all three services up
    python mock_server.py --down grade    # simulate the grade node being offline
    python mock_server.py --down auth course

Login with any user from common/seed_data.py (password: "password").
State is in memory and resets on restart.
"""
import argparse
from concurrent import futures

import grpc

import enrollment_pb2 as pb
import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data

# ---- in-memory state ----
COURSES = {c["code"]: dict(c) for c in seed_data.COURSES}
ENROLLED = set(seed_data.ENROLLMENTS)                      # {(student, code)}
GRADES = {(s, c): g for s, c, g in seed_data.GRADES}       # {(student, code): grade}


def _enrolled_count(code):
    return sum(1 for _, c in ENROLLED if c == code)


class MockAuth(rpc.AuthServiceServicer):
    def Login(self, request, context):
        user = seed_data.USERS.get(request.username)
        if not user or user["password"] != request.password:
            return pb.LoginReply(ok=False, msg="Invalid username or password")
        token = jwt_util.make(request.username, user["role"])
        return pb.LoginReply(ok=True, jwt=token, role=user["role"], msg="[mock] logged in")


class MockCourse(rpc.CourseServiceServicer):
    def ListCourses(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if not claims:
            return pb.CourseList(ok=False, msg="Not logged in / token expired")
        me = claims["sub"]
        out = []
        for c in COURSES.values():
            n = _enrolled_count(c["code"])
            out.append(pb.Course(
                code=c["code"], title=c["title"], slots=c["slots"], enrolled=n,
                is_open=c["is_open"] and n < c["slots"],
                i_am_enrolled=(me, c["code"]) in ENROLLED,
            ))
        return pb.CourseList(ok=True, courses=out)

    def Enroll(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if not claims:
            return pb.Result(ok=False, msg="Not logged in / token expired")
        if claims["role"] != "student":
            return pb.Result(ok=False, msg="Only students can enroll")
        c = COURSES.get(request.course_code)
        if not c:
            return pb.Result(ok=False, msg="No such course")
        key = (claims["sub"], c["code"])
        if key in ENROLLED:
            return pb.Result(ok=False, msg="Already enrolled")
        if not c["is_open"] or _enrolled_count(c["code"]) >= c["slots"]:
            return pb.Result(ok=False, msg="Course is closed or full")
        ENROLLED.add(key)
        return pb.Result(ok=True, msg=f"[mock] enrolled in {c['code']}")


class MockGrade(rpc.GradeServiceServicer):
    def GetGrades(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if not claims:
            return pb.GradeList(ok=False, msg="Not logged in / token expired")
        me = claims["sub"]
        out = [pb.Grade(course_code=c, grade=g) for (s, c), g in GRADES.items() if s == me]
        return pb.GradeList(ok=True, grades=out)

    def UploadGrade(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if not claims:
            return pb.Result(ok=False, msg="Not logged in / token expired")
        if claims["role"] != "faculty":
            return pb.Result(ok=False, msg="Only faculty can upload grades")
        if request.student not in seed_data.USERS:
            return pb.Result(ok=False, msg="No such student")
        GRADES[(request.student, request.course_code)] = request.grade
        return pb.Result(ok=True, msg=f"[mock] {request.student} {request.course_code} = {request.grade}")


SERVICES = {
    "auth": (rpc.add_AuthServiceServicer_to_server, MockAuth, config.AUTH_PORT),
    "course": (rpc.add_CourseServiceServicer_to_server, MockCourse, config.COURSE_PORT),
    "grade": (rpc.add_GradeServiceServicer_to_server, MockGrade, config.GRADE_PORT),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--down", nargs="*", default=[], choices=list(SERVICES),
                    help="services to leave offline (to test 'service unavailable' pages)")
    args = ap.parse_args()

    servers = []
    for name, (add_fn, cls, port) in SERVICES.items():
        if name in args.down:
            print(f"  {name:<6} DOWN (simulated)")
            continue
        s = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        add_fn(cls(), s)
        s.add_insecure_port(f"0.0.0.0:{port}")
        s.start()
        servers.append(s)
        print(f"  {name:<6} mock on :{port}")

    print("Mock running. Ctrl+C to stop.")
    try:
        for s in servers:
            s.wait_for_termination()
        if not servers:
            input("All services down. Press Enter to exit.")
    except KeyboardInterrupt:
        for s in servers:
            s.stop(0)


if __name__ == "__main__":
    main()
