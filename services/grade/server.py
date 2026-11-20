from concurrent import futures
from pathlib import Path
import sqlite3
import grpc

from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util, seed_data

DB_PATH = Path(__file__).parent / "grades.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grades (
                student TEXT NOT NULL,
                course_code TEXT NOT NULL,
                grade TEXT NOT NULL,
                PRIMARY KEY (student, course_code)
            )
            """
        )
        # Seed only if table is empty so updates persist across restarts
        count = conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO grades (student, course_code, grade) VALUES (?, ?, ?)",
                seed_data.GRADES,
            )


class GradeService(rpc.GradeServiceServicer):
    def GetGrades(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if claims is None:
            return pb.GradeList(ok=False, msg="Invalid or missing token")

        username = claims.get("sub") or claims.get("user")
        role = claims.get("role")
        if role != "student":
            return pb.GradeList(ok=False, msg="Only students can view their grades")

        try:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT course_code, grade FROM grades WHERE student = ? ORDER BY course_code",
                    (username,),
                ).fetchall()

            grades = [
                pb.Grade(course_code=row["course_code"], grade=row["grade"])
                for row in rows
            ]
            return pb.GradeList(ok=True, msg="OK", grades=grades)
        except Exception as e:
            return pb.GradeList(ok=False, msg=f"Database error: {e}")

    def UploadGrade(self, request, context):
        claims = jwt_util.claims_or_none(request.jwt)
        if claims is None:
            return pb.Result(ok=False, msg="Invalid or missing token")

        if claims.get("role") != "faculty":
            return pb.Result(ok=False, msg="Faculty role required")

        student = request.student.strip()
        course_code = request.course_code.strip()
        grade = request.grade.strip()

        if not student or not course_code or not grade:
            return pb.Result(ok=False, msg="Student, course_code, and grade are required")

        user_info = seed_data.USERS.get(student)
        if not user_info or user_info.get("role") != "student":
            return pb.Result(ok=False, msg=f"Student '{student}' does not exist")

        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO grades (student, course_code, grade)
                    VALUES (?, ?, ?)
                    ON CONFLICT(student, course_code)
                    DO UPDATE SET grade = excluded.grade
                    """,
                    (student, course_code, grade),
                )
            return pb.Result(ok=True, msg=f"Grade saved for {student} in {course_code}")
        except Exception as e:
            return pb.Result(ok=False, msg=f"Database error: {e}")


def serve():
    init_db()
    port = getattr(config, "GRADE_PORT", 50053)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    rpc.add_GradeServiceServicer_to_server(GradeService(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    print(f"GradeService running on 0.0.0.0:{port} (db: {DB_PATH})")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()