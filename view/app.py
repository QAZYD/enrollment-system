"""Flask MVC View node (Person 4) for the Distributed Enrollment System."""

from functools import wraps
import hmac
import os
import secrets

from flask import (
    Flask,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from common import config, jwt_util
from view.grpc_client import EnrollmentGrpcClient

JWT_COOKIE_NAME = "jwt_token"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def create_app(rpc_client=None, test_config: dict | None = None) -> Flask:
    """Create and configure the stateless Flask MVC View application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # FLASK_SECRET_KEY signs Flask's stateless session cookie (flash messages + CSRF token).
    cookie_secure = _env_bool("COOKIE_SECURE", default=False)
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-flask-secret-change-me"),
        COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
    )
    if test_config:
        app.config.update(test_config)
        if "COOKIE_SECURE" in test_config and "SESSION_COOKIE_SECURE" not in test_config:
            app.config["SESSION_COOKIE_SECURE"] = bool(app.config["COOKIE_SECURE"])

    client = rpc_client or EnrollmentGrpcClient()

    def get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    @app.context_processor
    def inject_template_globals():
        return {
            "csrf_token": get_csrf_token,
            "current_user": getattr(g, "user", None),
        }

    @app.before_request
    def load_user_and_verify_csrf():
        g.user = None
        g.jwt = None
        g.clear_invalid_jwt = False

        raw_token = request.cookies.get(JWT_COOKIE_NAME)
        if raw_token:
            claims = jwt_util.claims_or_none(raw_token)
            if (
                isinstance(claims, dict)
                and claims.get("sub")
                and claims.get("role") in ("student", "faculty")
            ):
                g.jwt = raw_token
                g.user = {
                    "username": claims["sub"],
                    "role": claims["role"],
                }
            else:
                g.clear_invalid_jwt = True

        if request.method == "POST":
            expected = session.get("csrf_token", "")
            submitted = request.form.get("csrf_token", "")
            if not expected or not submitted or not hmac.compare_digest(expected, submitted):
                return (
                    render_template(
                        "error.html",
                        title="Invalid form request",
                        message="Your form token is missing or expired. Reload the page and try again.",
                        back_url=url_for("courses") if g.user else url_for("login"),
                        back_label="Back to Courses" if g.user else "Back to Sign in",
                    ),
                    400,
                )

    @app.after_request
    def clear_invalid_cookie_if_needed(response):
        if getattr(g, "clear_invalid_jwt", False):
            response.delete_cookie(JWT_COOKIE_NAME, path="/", samesite="Lax")
        return response

    def require_auth(roles: tuple[str, ...] | None = None):
        def decorator(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                if g.user is None:
                    if g.clear_invalid_jwt:
                        flash("Your session is invalid or expired. Sign in again.", "error")
                    return redirect(url_for("login"))
                if roles is not None and g.user["role"] not in roles:
                    role_label = "student" if roles == ("student",) else "faculty"
                    return (
                        render_template(
                            "error.html",
                            title="Access denied",
                            message=f"This page is restricted to {role_label} accounts.",
                            back_url=url_for("courses"),
                            back_label="Return to Courses",
                        ),
                        403,
                    )
                return fn(*args, **kwargs)

            return wrapper

        return decorator

    @app.get("/")
    def index():
        if g.user:
            return redirect(url_for("courses"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if g.user:
                return redirect(url_for("courses"))
            return render_template("login.html", username="")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return (
                render_template(
                    "login.html",
                    username=username,
                    error_msg="Enter both your username and password.",
                ),
                400,
            )

        outcome = client.login(username, password)
        if not outcome.available:
            return (
                render_template(
                    "login.html",
                    username=username,
                    service_error=(
                        "Auth service unavailable. Sign-in is temporarily offline; "
                        "please try again once the Auth node is running."
                    ),
                ),
                503,
            )

        if not outcome.ok:
            return (
                render_template(
                    "login.html",
                    username=username,
                    error_msg=outcome.msg,
                ),
                401,
            )

        g.clear_invalid_jwt = False
        session["csrf_token"] = secrets.token_urlsafe(32)
        response = make_response(redirect(url_for("courses")))
        response.set_cookie(
            JWT_COOKIE_NAME,
            outcome.data["jwt"],
            httponly=True,
            samesite="Lax",
            secure=bool(app.config["COOKIE_SECURE"]),
            max_age=jwt_util.TTL_SECONDS,
            path="/",
        )
        return response

    @app.post("/logout")
    def logout():
        g.clear_invalid_jwt = False
        g.user = None
        g.jwt = None
        session["csrf_token"] = secrets.token_urlsafe(32)
        flash("You have been signed out.", "success")
        response = make_response(redirect(url_for("login")))
        response.delete_cookie(JWT_COOKIE_NAME, path="/", samesite="Lax")
        return response

    @app.get("/courses")
    @require_auth()
    def courses():
        outcome = client.list_courses(g.jwt)
        if not outcome.available:
            return (
                render_template(
                    "courses.html",
                    active_page="courses",
                    courses=[],
                    service_error=(
                        "Course service unavailable. Course listings and enrollment "
                        "are temporarily offline, while other sections remain usable."
                    ),
                ),
                503,
            )

        if not outcome.ok:
            return render_template(
                "courses.html",
                active_page="courses",
                courses=[],
                error_msg=outcome.msg,
            )

        items = []
        for c in outcome.data:
            is_full = c.slots > 0 and c.enrolled >= c.slots
            if is_full:
                status = "Full"
            elif c.is_open:
                status = "Open"
            else:
                status = "Closed"

            can_enroll = (
                g.user["role"] == "student"
                and not c.i_am_enrolled
                and c.is_open
                and not is_full
            )
            items.append(
                {
                    "code": c.code,
                    "title": c.title,
                    "enrolled": c.enrolled,
                    "slots": c.slots,
                    "status": status,
                    "i_am_enrolled": c.i_am_enrolled,
                    "can_enroll": can_enroll,
                }
            )

        return render_template(
            "courses.html",
            active_page="courses",
            courses=items,
        )

    @app.post("/enroll")
    @require_auth(roles=("student",))
    def enroll():
        course_code = request.form.get("course_code", "").strip()
        if not course_code:
            flash("Missing course code.", "error")
            return redirect(url_for("courses"))

        outcome = client.enroll(g.jwt, course_code)
        if not outcome.available:
            flash(
                "Course service unavailable. Enrollment could not be completed.",
                "error",
            )
        elif not outcome.ok:
            flash(outcome.msg, "error")
        else:
            flash(outcome.msg or f"Enrolled in {course_code}.", "success")
        return redirect(url_for("courses"))

    @app.get("/grades")
    @require_auth(roles=("student",))
    def grades():
        outcome = client.get_grades(g.jwt)
        if not outcome.available:
            return (
                render_template(
                    "grades.html",
                    active_page="grades",
                    grades=[],
                    service_error=(
                        "Grade service unavailable. Your grade records are temporarily "
                        "offline, while Courses remains available."
                    ),
                ),
                503,
            )

        if not outcome.ok:
            return render_template(
                "grades.html",
                active_page="grades",
                grades=[],
                error_msg=outcome.msg,
            )

        return render_template(
            "grades.html",
            active_page="grades",
            grades=outcome.data,
        )

    @app.route("/grades/upload", methods=["GET", "POST"])
    @require_auth(roles=("faculty",))
    def upload_grade():
        if request.method == "GET":
            return render_template(
                "upload_grade.html",
                active_page="upload",
                form_values={"student": "", "course_code": "", "grade": ""},
            )

        form_values = {
            "student": request.form.get("student", "").strip(),
            "course_code": request.form.get("course_code", "").strip(),
            "grade": request.form.get("grade", "").strip(),
        }

        if not all(form_values.values()):
            return (
                render_template(
                    "upload_grade.html",
                    active_page="upload",
                    form_values=form_values,
                    error_msg="Enter student username, course code, and grade.",
                ),
                400,
            )

        outcome = client.upload_grade(
            g.jwt,
            form_values["student"],
            form_values["course_code"],
            form_values["grade"],
        )
        if not outcome.available:
            return (
                render_template(
                    "upload_grade.html",
                    active_page="upload",
                    form_values=form_values,
                    service_error=(
                        "Grade service unavailable. Grade submission is temporarily "
                        "offline; your form entries have been kept."
                    ),
                ),
                503,
            )

        if not outcome.ok:
            return (
                render_template(
                    "upload_grade.html",
                    active_page="upload",
                    form_values=form_values,
                    error_msg=outcome.msg,
                ),
                400,
            )

        flash(
            outcome.msg
            or (
                f"Saved grade {form_values['grade']} for "
                f"{form_values['student']} in {form_values['course_code']}."
            ),
            "success",
        )
        return redirect(url_for("upload_grade"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.VIEW_PORT, debug=False)
