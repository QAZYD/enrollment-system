"""Run `python -m services.course.test_course` with only the local Course node running.

Uses courses.db beside the service to create and remove unique test fixtures.
RPCs still use COURSE_ADDR; run this client on the Course machine.
"""
import uuid
from concurrent import futures
from contextlib import closing

import grpc

from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data
from services.course.server import DB_PATH, connect


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main():
    prefix = "TEST_" + uuid.uuid4().hex
    opened, closed, full, race = [prefix + suffix for suffix in ("O", "C", "F", "R")]
    codes = (opened, closed, full, race)
    tok = jwt_util.make("student1", "student")
    faculty = jwt_util.make("faculty1", "faculty")
    if not DB_PATH.is_file():
        raise SystemExit("Start the Course server before running this client.")
    with closing(connect()) as db:
        with db:
            db.executemany("INSERT INTO courses VALUES (?, ?, ?, ?)", [
                (opened, "Test open", 2, 1), (closed, "Test closed", 2, 0),
                (full, "Test full", 1, 1), (race, "Test last seat", 1, 1),
            ])
            db.execute("INSERT INTO enrollments VALUES (?, ?)", ("student2", full))
        try:
            with grpc.insecure_channel(config.COURSE_ADDR) as channel:
                stub = rpc.CourseServiceStub(channel)

                def listing(token=tok):
                    return stub.ListCourses(pb.Token(jwt=token), timeout=2)

                def enroll(code, token=tok):
                    return stub.Enroll(pb.EnrollRequest(jwt=token, course_code=code), timeout=2)

                def rejected(reply, label, expected):
                    check(not reply.ok and expected in reply.msg.lower(), label)

                before = listing()
                check(before.ok, "ListCourses succeeds without Auth or Grade")
                courses = {c.code: c for c in before.courses}
                seed_codes = {course["code"] for course in seed_data.COURSES}
                check(seed_codes.union(codes) <= courses.keys(), "Seed and test courses are listed")
                check(not courses[closed].is_open and not courses[full].is_open,
                      "Closed and full courses are unavailable")
                check(courses[opened].is_open and not courses[opened].i_am_enrolled,
                      "Open course has a seat for student1")
                rejected(listing("invalid"), "Invalid JWT: ListCourses", "token")
                rejected(enroll(opened, "invalid"), "Invalid JWT: Enroll", "token")
                rejected(enroll(opened, faculty), "Faculty cannot enroll", "student")
                rejected(enroll(prefix + "missing"), "Unknown course", "no such course")
                rejected(enroll(closed), "Closed course", "closed")
                rejected(enroll(full), "Full course", "full")
                check(enroll(opened).ok, "Student enrollment succeeds")
                after = listing()
                check(after.ok, "ListCourses after enrollment")
                updated = next(c for c in after.courses if c.code == opened)
                check(updated.enrolled == courses[opened].enrolled + 1
                      and updated.i_am_enrolled, "Count increases by one and caller is enrolled")
                rejected(enroll(opened), "Duplicate enrollment", "already enrolled")
                with futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(
                        lambda user: enroll(race, jwt_util.make(user, "student")),
                        ["student2", "student3"],
                    ))
                check(sum(r.ok for r in results) == 1
                      and all(r.ok or "full" in r.msg.lower() for r in results),
                      "Concurrent requests cannot overbook the last seat")
                final = listing()
                check(final.ok and next(c for c in final.courses if c.code == race).enrolled == 1,
                      "Exactly one enrollment saved for last seat")
        finally:
            with db:
                db.executemany("DELETE FROM enrollments WHERE course_code = ?", [(c,) for c in codes])
                db.executemany("DELETE FROM courses WHERE code = ?", [(c,) for c in codes])
    print("All Course client checks passed; disposable test data removed.")


if __name__ == "__main__":
    main()
