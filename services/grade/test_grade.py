import grpc
from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util


def main():
    addr = getattr(config, "GRADE_ADDR", "localhost:50053")
    channel = grpc.insecure_channel(addr)
    stub = rpc.GradeServiceStub(channel)

    student_tok = jwt_util.make("student1", "student")
    faculty_tok = jwt_util.make("faculty1", "faculty")

    print("1. Invalid token -> expect ok=False:")
    print(stub.GetGrades(pb.Token(jwt="bad-token"), timeout=2))

    print("\n2. Student1 GetGrades -> expect CS101 (4.0), MATH101 (3.5):")
    print(stub.GetGrades(pb.Token(jwt=student_tok), timeout=2))

    print("\n3. Student tries UploadGrade -> expect ok=False:")
    print(
        stub.UploadGrade(
            pb.UploadRequest(jwt=student_tok, student="student1", course_code="CS102", grade="4.0"),
            timeout=2,
        )
    )

    print("\n4. Faculty uploads for non-existent student -> expect ok=False:")
    print(
        stub.UploadGrade(
            pb.UploadRequest(jwt=faculty_tok, student="ghost", course_code="CS102", grade="3.0"),
            timeout=2,
        )
    )

    print("\n5. Faculty inserts new grade for student1 -> expect ok=True:")
    print(
        stub.UploadGrade(
            pb.UploadRequest(jwt=faculty_tok, student="student1", course_code="CS102", grade="3.0"),
            timeout=2,
        )
    )

    print("\n6. Faculty updates existing grade for student1 -> expect ok=True:")
    print(
        stub.UploadGrade(
            pb.UploadRequest(jwt=faculty_tok, student="student1", course_code="CS102", grade="4.0"),
            timeout=2,
        )
    )

    print("\n7. Student1 GetGrades after upload -> expect CS102 (4.0):")
    print(stub.GetGrades(pb.Token(jwt=student_tok), timeout=2))


if __name__ == "__main__":
    main()