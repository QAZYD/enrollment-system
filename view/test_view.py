"""Automated tests for the Person 4 Flask MVC View node."""

from dataclasses import dataclass
import re
import time
import unittest
from unittest.mock import MagicMock, patch

import grpc
import jwt

import enrollment_pb2 as pb
from common import config, jwt_util
from view.app import JWT_COOKIE_NAME, create_app
from view.grpc_client import EnrollmentGrpcClient, RpcOutcome


class _FakeRpcError(grpc.RpcError):
    """Minimal grpc.RpcError subclass for simulating offline backends."""


@dataclass
class _StubCourse:
    code: str
    title: str
    slots: int
    enrolled: int
    is_open: bool
    i_am_enrolled: bool


@dataclass
class _StubGrade:
    course_code: str
    grade: str


class _FakeClient:
    """Controllable in-memory double matching EnrollmentGrpcClient's interface."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.auth_down = False
        self.course_down = False
        self.grade_down = False
        self.login_outcome: RpcOutcome | None = None
        self.courses_outcome: RpcOutcome | None = None
        self.enroll_outcome: RpcOutcome | None = None
        self.grades_outcome: RpcOutcome | None = None
        self.upload_outcome: RpcOutcome | None = None

    def login(self, username: str, password: str) -> RpcOutcome:
        self.calls.append(("login", username, password))
        if self.auth_down:
            return RpcOutcome(
                available=False, ok=False, msg="Auth service unavailable.", service="Auth"
            )
        if self.login_outcome is not None:
            return self.login_outcome
        role = "faculty" if username.startswith("faculty") else "student"
        return RpcOutcome(
            available=True,
            ok=True,
            msg="Logged in",
            data={"jwt": jwt_util.make(username, role), "role": role},
            service="Auth",
        )

    def list_courses(self, jwt_token: str) -> RpcOutcome:
        self.calls.append(("list_courses", jwt_token))
        if self.course_down:
            return RpcOutcome(
                available=False,
                ok=False,
                msg="Course service unavailable.",
                service="Course",
            )
        if self.courses_outcome is not None:
            return self.courses_outcome
        return RpcOutcome(
            available=True,
            ok=True,
            data=[
                _StubCourse("CS101", "Intro to Programming", 30, 1, True, True),
                _StubCourse("CS102", "Data Structures", 2, 1, True, False),
                _StubCourse("CS103", "Operating Systems", 2, 2, False, False),
                _StubCourse("STDISCM", "Distributed Computing", 20, 0, False, False),
            ],
            service="Course",
        )

    def enroll(self, jwt_token: str, course_code: str) -> RpcOutcome:
        self.calls.append(("enroll", jwt_token, course_code))
        if self.course_down:
            return RpcOutcome(
                available=False,
                ok=False,
                msg="Course service unavailable.",
                service="Course",
            )
        if self.enroll_outcome is not None:
            return self.enroll_outcome
        return RpcOutcome(
            available=True, ok=True, msg=f"Enrolled in {course_code}.", service="Course"
        )

    def get_grades(self, jwt_token: str) -> RpcOutcome:
        self.calls.append(("get_grades", jwt_token))
        if self.grade_down:
            return RpcOutcome(
                available=False,
                ok=False,
                msg="Grade service unavailable.",
                service="Grade",
            )
        if self.grades_outcome is not None:
            return self.grades_outcome
        return RpcOutcome(
            available=True,
            ok=True,
            data=[
                _StubGrade("CS101", "4.0"),
                _StubGrade("MATH101", "3.5"),
            ],
            service="Grade",
        )

    def upload_grade(
        self, jwt_token: str, student: str, course_code: str, grade: str
    ) -> RpcOutcome:
        self.calls.append(("upload_grade", jwt_token, student, course_code, grade))
        if self.grade_down:
            return RpcOutcome(
                available=False,
                ok=False,
                msg="Grade service unavailable.",
                service="Grade",
            )
        if self.upload_outcome is not None:
            return self.upload_outcome
        return RpcOutcome(
            available=True,
            ok=True,
            msg=f"Saved {student} {course_code} = {grade}.",
            service="Grade",
        )


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token hidden field not found in HTML response.")
    return match.group(1)


class ViewAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rpc = _FakeClient()
        self.app = create_app(
            rpc_client=self.rpc,
            test_config={"TESTING": True, "SECRET_KEY": "test-flask-secret"},
        )
        self.client = self.app.test_client()

    def _get_csrf(self, path: str = "/login") -> str:
        resp = self.client.get(path)
        return _extract_csrf(resp.get_data(as_text=True))

    def _set_jwt_cookie(self, token: str) -> None:
        self.client.set_cookie(JWT_COOKIE_NAME, token, domain="localhost")

    def _get_cookie(self, name: str):
        return self.client.get_cookie(name, domain="localhost")

    def test_boot_and_login_page_work_when_all_backends_down(self) -> None:
        self.rpc.auth_down = True
        self.rpc.course_down = True
        self.rpc.grade_down = True

        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Sign in", resp.get_data(as_text=True))
        self.assertEqual(self.rpc.calls, [])

    def test_login_success_sets_httponly_samesite_cookie_and_redirects(self) -> None:
        token = self._get_csrf("/login")
        resp = self.client.post(
            "/login",
            data={"csrf_token": token, "username": "student1", "password": "password"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/courses"))

        set_cookie_headers = resp.headers.getlist("Set-Cookie")
        jwt_header = next(
            h for h in set_cookie_headers if h.startswith(f"{JWT_COOKIE_NAME}=")
        )
        self.assertIn("HttpOnly", jwt_header)
        self.assertIn("SameSite=Lax", jwt_header)
        self.assertNotIn("Secure", jwt_header)

    def test_login_cookie_respects_cookie_secure_config(self) -> None:
        secure_app = create_app(
            rpc_client=self.rpc,
            test_config={
                "TESTING": True,
                "SECRET_KEY": "test-flask-secret",
                "COOKIE_SECURE": True,
            },
        )
        secure_client = secure_app.test_client()
        token = _extract_csrf(secure_client.get("/login").get_data(as_text=True))
        resp = secure_client.post(
            "/login",
            data={"csrf_token": token, "username": "student1", "password": "password"},
        )
        set_cookie_headers = resp.headers.getlist("Set-Cookie")
        jwt_header = next(
            h for h in set_cookie_headers if h.startswith(f"{JWT_COOKIE_NAME}=")
        )
        self.assertIn("Secure", jwt_header)

    def test_login_failure_preserves_username_without_repopulating_password(self) -> None:
        self.rpc.login_outcome = RpcOutcome(
            available=True, ok=False, msg="Invalid username or password", service="Auth"
        )
        token = self._get_csrf("/login")
        resp = self.client.post(
            "/login",
            data={"csrf_token": token, "username": "student1", "password": "wrong-pw"},
        )
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Invalid username or password", html)
        self.assertIn('value="student1"', html)
        self.assertNotIn("wrong-pw", html)

    def test_logout_post_clears_cookie_locally_and_get_rejected(self) -> None:
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        token = self._get_csrf("/courses")
        self.rpc.calls.clear()

        get_resp = self.client.get("/logout")
        self.assertEqual(get_resp.status_code, 405)

        self.rpc.auth_down = True
        post_resp = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(post_resp.status_code, 302)
        self.assertTrue(post_resp.headers["Location"].endswith("/login"))
        self.assertIsNone(self._get_cookie(JWT_COOKIE_NAME))
        self.assertEqual(self.rpc.calls, [])

    def test_invalid_or_expired_cookie_is_cleared_and_redirects_to_login(self) -> None:
        self._set_jwt_cookie("not-a-valid-jwt")
        resp1 = self.client.get("/courses")
        self.assertEqual(resp1.status_code, 302)
        self.assertTrue(resp1.headers["Location"].endswith("/login"))
        self.assertIsNone(self._get_cookie(JWT_COOKIE_NAME))

        expired = jwt.encode(
            {
                "sub": "student1",
                "role": "student",
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 3600,
            },
            jwt_util.SECRET,
            algorithm=jwt_util.ALGO,
        )
        self._set_jwt_cookie(expired)
        resp2 = self.client.get("/grades")
        self.assertEqual(resp2.status_code, 302)
        self.assertTrue(resp2.headers["Location"].endswith("/login"))
        self.assertIsNone(self._get_cookie(JWT_COOKIE_NAME))

    def test_generic_backend_ok_false_preserves_valid_cookie(self) -> None:
        valid_tok = jwt_util.make("student1", "student")
        self._set_jwt_cookie(valid_tok)
        self.rpc.courses_outcome = RpcOutcome(
            available=True, ok=False, msg="Database busy", service="Course"
        )
        resp = self.client.get("/courses")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Database busy", resp.get_data(as_text=True))
        self.assertEqual(self._get_cookie(JWT_COOKIE_NAME).value, valid_tok)

        csrf = self._get_csrf("/courses")
        self.rpc.enroll_outcome = RpcOutcome(
            available=True, ok=False, msg="Already enrolled", service="Course"
        )
        enroll_resp = self.client.post(
            "/enroll",
            data={"csrf_token": csrf, "course_code": "CS101"},
            follow_redirects=True,
        )
        self.assertIn("Already enrolled", enroll_resp.get_data(as_text=True))
        self.assertEqual(self._get_cookie(JWT_COOKIE_NAME).value, valid_tok)

        self.rpc.grades_outcome = RpcOutcome(
            available=True, ok=False, msg="Grade query failed", service="Grade"
        )
        grades_resp = self.client.get("/grades")
        self.assertEqual(grades_resp.status_code, 200)
        self.assertIn("Grade query failed", grades_resp.get_data(as_text=True))
        self.assertEqual(self._get_cookie(JWT_COOKIE_NAME).value, valid_tok)

        faculty_tok = jwt_util.make("faculty1", "faculty")
        self._set_jwt_cookie(faculty_tok)
        f_csrf = self._get_csrf("/grades/upload")
        self.rpc.upload_outcome = RpcOutcome(
            available=True, ok=False, msg="No such student", service="Grade"
        )
        up_resp = self.client.post(
            "/grades/upload",
            data={
                "csrf_token": f_csrf,
                "student": "ghost",
                "course_code": "CS101",
                "grade": "4.0",
            },
        )
        self.assertEqual(up_resp.status_code, 400)
        self.assertIn("No such student", up_resp.get_data(as_text=True))
        self.assertEqual(self._get_cookie(JWT_COOKIE_NAME).value, faculty_tok)

    def test_role_restrictions_and_faculty_read_only_courses(self) -> None:
        # Faculty: read-only courses, no enroll actions, blocked from /enroll and /grades
        self._set_jwt_cookie(jwt_util.make("faculty1", "faculty"))
        courses_resp = self.client.get("/courses")
        courses_html = courses_resp.get_data(as_text=True)
        self.assertEqual(courses_resp.status_code, 200)
        self.assertNotIn('action="/enroll"', courses_html)
        self.assertNotIn('name="course_code"', courses_html)
        self.assertNotIn('<th scope="col">Action</th>', courses_html)
        self.assertIn("Upload grade", courses_html)
        self.assertIn('<span class="role-badge">Faculty</span>', courses_html)
        self.assertIn("4 courses", courses_html)

        csrf = _extract_csrf(courses_html)
        self.rpc.calls.clear()

        enroll_resp = self.client.post(
            "/enroll", data={"csrf_token": csrf, "course_code": "CS102"}
        )
        self.assertEqual(enroll_resp.status_code, 403)

        grades_resp = self.client.get("/grades")
        self.assertEqual(grades_resp.status_code, 403)
        self.assertEqual(self.rpc.calls, [])

        # Student: blocked from /grades/upload GET and POST
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        student_csrf = self._get_csrf("/courses")
        self.rpc.calls.clear()

        up_get = self.client.get("/grades/upload")
        self.assertEqual(up_get.status_code, 403)

        up_post = self.client.post(
            "/grades/upload",
            data={
                "csrf_token": student_csrf,
                "student": "student1",
                "course_code": "CS101",
                "grade": "4.0",
            },
        )
        self.assertEqual(up_post.status_code, 403)
        self.assertEqual(self.rpc.calls, [])

    def test_csrf_rejection_on_every_post_route(self) -> None:
        # Establish a session cookie so expected csrf_token exists
        self._get_csrf("/login")

        for path, payload in [
            ("/login", {"username": "student1", "password": "password"}),
            ("/logout", {}),
        ]:
            resp = self.client.post(path, data=payload)
            self.assertEqual(resp.status_code, 400)
            resp_bad = self.client.post(path, data={**payload, "csrf_token": "bad"})
            self.assertEqual(resp_bad.status_code, 400)

        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        self.rpc.calls.clear()
        enroll_missing = self.client.post("/enroll", data={"course_code": "CS102"})
        self.assertEqual(enroll_missing.status_code, 400)

        self._set_jwt_cookie(jwt_util.make("faculty1", "faculty"))
        upload_missing = self.client.post(
            "/grades/upload",
            data={"student": "student1", "course_code": "CS101", "grade": "4.0"},
        )
        self.assertEqual(upload_missing.status_code, 400)
        self.assertEqual(self.rpc.calls, [])

    def test_courses_status_badges_and_enroll_button_gating(self) -> None:
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        resp = self.client.get("/courses")
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<span class="role-badge">Student</span>', html)
        self.assertIn("4 courses", html)
        self.assertIn("Enrolled", html)
        self.assertIn("Open", html)
        self.assertIn("Full", html)
        self.assertIn("Closed", html)
        # Only CS102 (open, not full, not enrolled) should have an Enroll action
        enroll_targets = re.findall(
            r'name="course_code"\s+value="([^"]+)"', html
        )
        self.assertEqual(enroll_targets, ["CS102"])

    def test_partial_failure_isolation_auth_down(self) -> None:
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        self.rpc.auth_down = True

        self.assertEqual(self.client.get("/courses").status_code, 200)
        self.assertEqual(self.client.get("/grades").status_code, 200)

        # Clear student cookie to test fresh login while Auth is down
        self.client.delete_cookie(JWT_COOKIE_NAME, domain="localhost")
        csrf = self._get_csrf("/login")
        login_resp = self.client.post(
            "/login",
            data={"csrf_token": csrf, "username": "student1", "password": "password"},
        )
        self.assertEqual(login_resp.status_code, 503)
        self.assertIn("Auth service unavailable", login_resp.get_data(as_text=True))

    def test_partial_failure_isolation_grade_down(self) -> None:
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        self.rpc.grade_down = True

        grades_resp = self.client.get("/grades")
        self.assertEqual(grades_resp.status_code, 503)
        self.assertIn("Grade service unavailable", grades_resp.get_data(as_text=True))

        courses_resp = self.client.get("/courses")
        self.assertEqual(courses_resp.status_code, 200)
        csrf = _extract_csrf(courses_resp.get_data(as_text=True))
        enroll_resp = self.client.post(
            "/enroll",
            data={"csrf_token": csrf, "course_code": "CS102"},
            follow_redirects=True,
        )
        self.assertEqual(enroll_resp.status_code, 200)
        self.assertIn("Enrolled in CS102", enroll_resp.get_data(as_text=True))

        self._set_jwt_cookie(jwt_util.make("faculty1", "faculty"))
        f_csrf = self._get_csrf("/grades/upload")
        up_resp = self.client.post(
            "/grades/upload",
            data={
                "csrf_token": f_csrf,
                "student": "student1",
                "course_code": "CS101",
                "grade": "3.5",
            },
        )
        up_html = up_resp.get_data(as_text=True)
        self.assertEqual(up_resp.status_code, 503)
        self.assertIn("Grade service unavailable", up_html)
        self.assertIn('value="student1"', up_html)
        self.assertIn('value="CS101"', up_html)
        self.assertIn('value="3.5"', up_html)

    def test_partial_failure_isolation_course_down(self) -> None:
        self._set_jwt_cookie(jwt_util.make("student1", "student"))
        self.rpc.course_down = True

        courses_resp = self.client.get("/courses")
        self.assertEqual(courses_resp.status_code, 503)
        self.assertIn("Course service unavailable", courses_resp.get_data(as_text=True))

        csrf = _extract_csrf(courses_resp.get_data(as_text=True))
        enroll_resp = self.client.post(
            "/enroll",
            data={"csrf_token": csrf, "course_code": "CS102"},
            follow_redirects=True,
        )
        self.assertIn("Course service unavailable", enroll_resp.get_data(as_text=True))

        grades_resp = self.client.get("/grades")
        self.assertEqual(grades_resp.status_code, 200)
        self.assertIn("4.0", grades_resp.get_data(as_text=True))

        self._set_jwt_cookie(jwt_util.make("faculty1", "faculty"))
        self.rpc.calls.clear()
        up_get = self.client.get("/grades/upload")
        self.assertEqual(up_get.status_code, 200)
        self.assertEqual(self.rpc.calls, [])
        f_csrf = _extract_csrf(up_get.get_data(as_text=True))
        up_post = self.client.post(
            "/grades/upload",
            data={
                "csrf_token": f_csrf,
                "student": "student1",
                "course_code": "CS101",
                "grade": "4.0",
            },
            follow_redirects=True,
        )
        self.assertEqual(up_post.status_code, 200)
        self.assertIn("Saved student1 CS101 = 4.0", up_post.get_data(as_text=True))


class GrpcClientDeadlineTests(unittest.TestCase):
    def test_every_rpc_passes_configured_timeout_and_catches_rpc_error(self) -> None:
        client = EnrollmentGrpcClient()
        self.assertEqual(client.timeout, config.RPC_TIMEOUT)

        with patch("view.grpc_client.grpc.insecure_channel") as mock_ch, patch(
            "view.grpc_client.rpc.AuthServiceStub"
        ) as auth_stub_cls, patch(
            "view.grpc_client.rpc.CourseServiceStub"
        ) as course_stub_cls, patch(
            "view.grpc_client.rpc.GradeServiceStub"
        ) as grade_stub_cls:
            channel = MagicMock()
            mock_ch.return_value.__enter__.return_value = channel

            auth_stub = auth_stub_cls.return_value
            auth_stub.Login.return_value = pb.LoginReply(
                ok=True, jwt="tok", role="student", msg="ok"
            )
            course_stub = course_stub_cls.return_value
            course_stub.ListCourses.return_value = pb.CourseList(ok=True, courses=[])
            course_stub.Enroll.return_value = pb.Result(ok=True, msg="ok")
            grade_stub = grade_stub_cls.return_value
            grade_stub.GetGrades.return_value = pb.GradeList(ok=True, grades=[])
            grade_stub.UploadGrade.return_value = pb.Result(ok=True, msg="ok")

            self.assertTrue(client.login("student1", "password").ok)
            self.assertTrue(client.list_courses("tok").ok)
            self.assertTrue(client.enroll("tok", "CS101").ok)
            self.assertTrue(client.get_grades("tok").ok)
            self.assertTrue(client.upload_grade("tok", "student1", "CS101", "4.0").ok)

            self.assertEqual(auth_stub.Login.call_args.kwargs["timeout"], config.RPC_TIMEOUT)
            self.assertEqual(
                course_stub.ListCourses.call_args.kwargs["timeout"], config.RPC_TIMEOUT
            )
            self.assertEqual(course_stub.Enroll.call_args.kwargs["timeout"], config.RPC_TIMEOUT)
            self.assertEqual(
                grade_stub.GetGrades.call_args.kwargs["timeout"], config.RPC_TIMEOUT
            )
            self.assertEqual(
                grade_stub.UploadGrade.call_args.kwargs["timeout"], config.RPC_TIMEOUT
            )

            auth_stub.Login.side_effect = _FakeRpcError()
            course_stub.ListCourses.side_effect = _FakeRpcError()
            course_stub.Enroll.side_effect = _FakeRpcError()
            grade_stub.GetGrades.side_effect = _FakeRpcError()
            grade_stub.UploadGrade.side_effect = _FakeRpcError()

            for res in [
                client.login("student1", "password"),
                client.list_courses("tok"),
                client.enroll("tok", "CS101"),
                client.get_grades("tok"),
                client.upload_grade("tok", "student1", "CS101", "4.0"),
            ]:
                self.assertFalse(res.available)
                self.assertFalse(res.ok)
                self.assertIn("unavailable", res.msg.lower())


if __name__ == "__main__":
    unittest.main()
