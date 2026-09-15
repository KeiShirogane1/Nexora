from app.Http.Controllers.ojt_evaluation import _classroom_evaluation_readiness
from app.Models.db import get_db_connection


SUPERVISOR_ID = 99841
STUDENT_A_ID = 99842
STUDENT_B_ID = 99843
CLASS_CODE = "NXR-EVALGATE"


def _cleanup():
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id FROM classrooms WHERE code = ?",
            (CLASS_CODE,),
        ).fetchone()
        if classroom:
            class_id = int(classroom["id"] if "id" in classroom.keys() else classroom[0])
            conn.execute("DELETE FROM attendance WHERE classroom_id = ?", (class_id,))
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (class_id,))
            conn.execute("DELETE FROM classroom_internship_details WHERE classroom_id = ?", (class_id,))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (class_id,))
        conn.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (SUPERVISOR_ID, STUDENT_A_ID, STUDENT_B_ID))
        conn.commit()
    finally:
        conn.close()


def _setup_classroom():
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password, role, status) VALUES (?, ?, ?, 'supervisor', 'active')",
            (SUPERVISOR_ID, "eval_gate_supervisor", "pytest-only"),
        )
        conn.execute(
            "INSERT INTO users (id, username, password, role, status) VALUES (?, ?, ?, 'student', 'active')",
            (STUDENT_A_ID, "eval_gate_student_a", "pytest-only"),
        )
        conn.execute(
            "INSERT INTO users (id, username, password, role, status) VALUES (?, ?, ?, 'student', 'active')",
            (STUDENT_B_ID, "eval_gate_student_b", "pytest-only"),
        )
        conn.execute(
            """
            INSERT INTO classrooms
            (supervisor_id, name, section, description, code, classroom_type, archived)
            VALUES (?, 'Evaluation Gate', 'OJT-A', 'readiness regression', ?, 'internship', 0)
            """,
            (SUPERVISOR_ID, CLASS_CODE),
        )
        classroom = conn.execute(
            "SELECT id FROM classrooms WHERE code = ?",
            (CLASS_CODE,),
        ).fetchone()
        class_id = int(classroom["id"] if "id" in classroom.keys() else classroom[0])
        conn.execute(
            """
            INSERT INTO classroom_internship_details
            (classroom_id, internship_title, company_name, work_arrangement,
             schedule_type, hours_mode, compensation, required_hours,
             internship_description, hours_per_day, required_days,
             attendance_days, shift_start_time, shift_end_time)
            VALUES (?, 'Evaluation Gate', 'Nexora Test Company', 'On-site',
                    'weekly', 'specified', 'Unpaid', 24,
                    'Regression fixture for evaluation readiness.', 8, 3,
                    'mon,tue,wed,thu,fri,sat', '09:00', '17:00')
            """,
            (class_id,),
        )
        conn.execute(
            "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)",
            (class_id, STUDENT_A_ID),
        )
        conn.execute(
            "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)",
            (class_id, STUDENT_B_ID),
        )

        for student_id, dates in (
            (STUDENT_A_ID, ("2026-09-01 09:00:00", "2026-09-02 09:00:00", "2026-09-03 09:00:00")),
            (STUDENT_B_ID, ("2026-09-01 09:00:00", "2026-09-02 09:00:00")),
        ):
            for clock_in in dates:
                conn.execute(
                    """
                    INSERT INTO attendance
                    (student_id, clock_in, clock_out, hours_rendered, status, classroom_id)
                    VALUES (?, ?, ?, 8, 'Completed', ?)
                    """,
                    (student_id, clock_in, clock_in, class_id),
                )
        conn.commit()
        return class_id
    finally:
        conn.close()


def test_evaluation_unlocks_only_when_all_interns_reach_required_days():
    _cleanup()
    class_id = _setup_classroom()
    try:
        state = _classroom_evaluation_readiness(SUPERVISOR_ID, class_id)
        assert state["configured"] is True
        assert state["available"] is False
        assert state["required_days"] == 3
        assert state["minimum_completed_days"] == 2
        assert state["days_left"] == 1

        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO attendance
                (student_id, clock_in, clock_out, hours_rendered, status, classroom_id)
                VALUES (?, '2026-09-03 09:00:00', '2026-09-03 17:00:00', 8, 'Completed', ?)
                """,
                (STUDENT_B_ID, class_id),
            )
            conn.commit()
        finally:
            conn.close()

        state = _classroom_evaluation_readiness(SUPERVISOR_ID, class_id)
        assert state["available"] is True
        assert state["minimum_completed_days"] == 3
        assert state["days_left"] == 0
    finally:
        _cleanup()
