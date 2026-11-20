"""Course node. Run from the project root: python -m services.course.server."""
import sqlite3
from concurrent import futures
from contextlib import closing
from pathlib import Path

import grpc

from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data

DB_PATH = Path(__file__).resolve().with_name("courses.db")


def connect():
    db = sqlite3.connect(DB_PATH, timeout=1)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with closing(connect()) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS courses (
            code TEXT PRIMARY KEY, title TEXT NOT NULL,
            slots INTEGER NOT NULL CHECK (slots >= 0),
            is_open INTEGER NOT NULL CHECK (is_open IN (0, 1)))""")
        db.execute("""CREATE TABLE IF NOT EXISTS enrollments (
            student TEXT NOT NULL, course_code TEXT NOT NULL REFERENCES courses(code),
            PRIMARY KEY (student, course_code))""")
        db.executemany(
            "INSERT OR IGNORE INTO courses VALUES (:code, :title, :slots, :is_open)",
            seed_data.COURSES,
        )
        db.executemany("INSERT OR IGNORE INTO enrollments VALUES (?, ?)",
                       seed_data.ENROLLMENTS)


class CourseService(rpc.CourseServiceServicer):
    def ListCourses(self, req, context):
        claims = jwt_util.claims_or_none(req.jwt)
        if claims is None:
            return pb.CourseList(ok=False, msg="Not logged in / token expired")
        if not claims.get("sub"):
            return pb.CourseList(ok=False, msg="Token is missing a username")
        try:
            with closing(connect()) as db:
                rows = db.execute("""
                    SELECT c.code, c.title, c.slots, c.is_open, COUNT(e.student),
                           COALESCE(MAX(e.student = ?), 0)
                    FROM courses c LEFT JOIN enrollments e ON e.course_code = c.code
                    GROUP BY c.code ORDER BY c.code
                """, (claims["sub"],)).fetchall()
            return pb.CourseList(ok=True, courses=[
                pb.Course(code=code, title=title, slots=slots, enrolled=count,
                          is_open=bool(opened and count < slots),
                          i_am_enrolled=bool(mine))
                for code, title, slots, opened, count, mine in rows
            ])
        except sqlite3.Error:
            return pb.CourseList(ok=False, msg="Could not read courses; please try again")

    def Enroll(self, req, context):
        claims = jwt_util.claims_or_none(req.jwt)
        if claims is None:
            return pb.Result(ok=False, msg="Not logged in / token expired")
        if claims.get("role") != "student":
            return pb.Result(ok=False, msg="Only students can enroll")
        if not claims.get("sub"):
            return pb.Result(ok=False, msg="Token is missing a username")
        try:
            with closing(connect()) as db, db:
                # Reserve the writer before checking seats, including across processes.
                db.execute("BEGIN IMMEDIATE")
                course = db.execute("SELECT slots, is_open FROM courses WHERE code = ?",
                                    (req.course_code,)).fetchone()
                if course is None:
                    return pb.Result(ok=False, msg="No such course")
                key = (claims["sub"], req.course_code)
                if db.execute("SELECT 1 FROM enrollments WHERE student = ? AND course_code = ?",
                              key).fetchone():
                    return pb.Result(ok=False, msg="Already enrolled")
                slots, opened = course
                if not opened:
                    return pb.Result(ok=False, msg="Course is closed")
                count = db.execute("SELECT COUNT(*) FROM enrollments WHERE course_code = ?",
                                   (req.course_code,)).fetchone()[0]
                if count >= slots:
                    return pb.Result(ok=False, msg="Course is full")
                db.execute("INSERT INTO enrollments VALUES (?, ?)", key)
            return pb.Result(ok=True, msg=f"Enrolled in {req.course_code}")
        except sqlite3.Error:
            return pb.Result(ok=False, msg="Could not save enrollment; please try again")


def main():
    init_db()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8),
                         options=[("grpc.so_reuseport", 0)])
    rpc.add_CourseServiceServicer_to_server(CourseService(), server)
    server.add_insecure_port(f"0.0.0.0:{config.COURSE_PORT}")
    server.start()
    print(f"Course service listening on port {config.COURSE_PORT}", flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(2).wait()


if __name__ == "__main__":
    main()
