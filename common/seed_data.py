"""Shared sample data so every service (and the mock) agrees on names and codes.
Each real service copies what it needs into its OWN SQLite db on startup/seed."""

# username -> password + role  (auth service)
USERS = {
    "student1": {"password": "password", "role": "student"},
    "student2": {"password": "password", "role": "student"},
    "student3": {"password": "password", "role": "student"},
    "faculty1": {"password": "password", "role": "faculty"},
}

# course service
COURSES = [
    {"code": "CS101", "title": "Intro to Programming", "slots": 30, "is_open": True},
    {"code": "CS102", "title": "Data Structures", "slots": 2, "is_open": True},
    {"code": "MATH101", "title": "Calculus I", "slots": 25, "is_open": True},
    {"code": "STDISCM", "title": "Distributed Computing", "slots": 20, "is_open": False},
]

# course service: (student, course_code) already enrolled
ENROLLMENTS = [
    ("student1", "CS101"),
    ("student2", "CS102"),
]

# grade service: (student, course_code, grade) from previous terms
GRADES = [
    ("student1", "MATH101", "3.5"),
    ("student1", "CS101", "4.0"),
    ("student2", "CS101", "2.5"),
]
