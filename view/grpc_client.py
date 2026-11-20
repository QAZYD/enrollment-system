"""Thin gRPC client wrapper for the Flask View node.

Every RPC uses ``timeout=config.RPC_TIMEOUT`` and catches ``grpc.RpcError`` so
unreachable backend nodes degrade cleanly into service-unavailable outcomes.
"""

from dataclasses import dataclass
from typing import Any

import grpc

import enrollment_pb2 as pb
import enrollment_pb2_grpc as rpc
from common import config


@dataclass(frozen=True)
class RpcOutcome:
    """Normalized result of a single backend gRPC request."""

    available: bool
    ok: bool
    msg: str = ""
    data: Any = None
    service: str = ""


class EnrollmentGrpcClient:
    """Stateless per-call gRPC client for Auth, Course, and Grade services."""

    def __init__(
        self,
        auth_addr: str | None = None,
        course_addr: str | None = None,
        grade_addr: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.auth_addr = auth_addr or config.AUTH_ADDR
        self.course_addr = course_addr or config.COURSE_ADDR
        self.grade_addr = grade_addr or config.GRADE_ADDR
        self.timeout = config.RPC_TIMEOUT if timeout is None else timeout

    def _call(self, service_name: str, addr: str, stub_cls, fn) -> RpcOutcome:
        try:
            with grpc.insecure_channel(addr) as channel:
                stub = stub_cls(channel)
                return fn(stub, self.timeout)
        except grpc.RpcError:
            return RpcOutcome(
                available=False,
                ok=False,
                msg=f"{service_name} service unavailable.",
                service=service_name,
            )

    def login(self, username: str, password: str) -> RpcOutcome:
        """Authenticate credentials against AuthService.Login."""

        def _invoke(stub, timeout: float) -> RpcOutcome:
            resp = stub.Login(
                pb.LoginRequest(username=username, password=password),
                timeout=timeout,
            )
            if resp.ok:
                return RpcOutcome(
                    available=True,
                    ok=True,
                    msg=resp.msg,
                    data={"jwt": resp.jwt, "role": resp.role},
                    service="Auth",
                )
            return RpcOutcome(
                available=True,
                ok=False,
                msg=resp.msg or "Sign-in failed.",
                service="Auth",
            )

        return self._call("Auth", self.auth_addr, rpc.AuthServiceStub, _invoke)

    def list_courses(self, jwt_token: str) -> RpcOutcome:
        """Fetch all courses via CourseService.ListCourses."""

        def _invoke(stub, timeout: float) -> RpcOutcome:
            resp = stub.ListCourses(pb.Token(jwt=jwt_token), timeout=timeout)
            if resp.ok:
                return RpcOutcome(
                    available=True,
                    ok=True,
                    msg=resp.msg,
                    data=list(resp.courses),
                    service="Course",
                )
            return RpcOutcome(
                available=True,
                ok=False,
                msg=resp.msg or "Could not load courses.",
                service="Course",
            )

        return self._call("Course", self.course_addr, rpc.CourseServiceStub, _invoke)

    def enroll(self, jwt_token: str, course_code: str) -> RpcOutcome:
        """Enroll the authenticated student via CourseService.Enroll."""

        def _invoke(stub, timeout: float) -> RpcOutcome:
            resp = stub.Enroll(
                pb.EnrollRequest(jwt=jwt_token, course_code=course_code),
                timeout=timeout,
            )
            return RpcOutcome(
                available=True,
                ok=resp.ok,
                msg=resp.msg or ("Enrolled." if resp.ok else "Enrollment failed."),
                service="Course",
            )

        return self._call("Course", self.course_addr, rpc.CourseServiceStub, _invoke)

    def get_grades(self, jwt_token: str) -> RpcOutcome:
        """Fetch the authenticated student's grades via GradeService.GetGrades."""

        def _invoke(stub, timeout: float) -> RpcOutcome:
            resp = stub.GetGrades(pb.Token(jwt=jwt_token), timeout=timeout)
            if resp.ok:
                return RpcOutcome(
                    available=True,
                    ok=True,
                    msg=resp.msg,
                    data=list(resp.grades),
                    service="Grade",
                )
            return RpcOutcome(
                available=True,
                ok=False,
                msg=resp.msg or "Could not load grades.",
                service="Grade",
            )

        return self._call("Grade", self.grade_addr, rpc.GradeServiceStub, _invoke)

    def upload_grade(
        self, jwt_token: str, student: str, course_code: str, grade: str
    ) -> RpcOutcome:
        """Create or update a student's grade via GradeService.UploadGrade."""

        def _invoke(stub, timeout: float) -> RpcOutcome:
            resp = stub.UploadGrade(
                pb.UploadRequest(
                    jwt=jwt_token,
                    student=student,
                    course_code=course_code,
                    grade=grade,
                ),
                timeout=timeout,
            )
            return RpcOutcome(
                available=True,
                ok=resp.ok,
                msg=resp.msg or ("Grade saved." if resp.ok else "Grade upload failed."),
                service="Grade",
            )

        return self._call("Grade", self.grade_addr, rpc.GradeServiceStub, _invoke)
