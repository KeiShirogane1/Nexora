from app.Models.db import get_db_connection


PROGRAM_ALIASES = {
    "bsit": "Bachelor of Science in Information Technology",
    "bs information technology": "Bachelor of Science in Information Technology",
    "bs in information technology": "Bachelor of Science in Information Technology",
    "bachelor of science in information technology": "Bachelor of Science in Information Technology",
    "bscs": "Bachelor of Science in Computer Science",
    "bs computer science": "Bachelor of Science in Computer Science",
    "bs in computer science": "Bachelor of Science in Computer Science",
    "bachelor of science in computer science": "Bachelor of Science in Computer Science",
    "bsis": "Bachelor of Science in Information Systems",
    "bs information systems": "Bachelor of Science in Information Systems",
    "bs in information systems": "Bachelor of Science in Information Systems",
    "bachelor of science in information systems": "Bachelor of Science in Information Systems",
    "bscpe": "Bachelor of Science in Computer Engineering",
    "bscpe.": "Bachelor of Science in Computer Engineering",
    "bs computer engineering": "Bachelor of Science in Computer Engineering",
    "bs in computer engineering": "Bachelor of Science in Computer Engineering",
    "bachelor of science in computer engineering": "Bachelor of Science in Computer Engineering",
}


def normalize_program_name(value):
    """Expand known course abbreviations while preserving valid custom programs."""
    program = str(value or "").strip()
    if not program:
        return program
    return PROGRAM_ALIASES.get(program.lower(), program)


def update_student_profile(student_id, data):

    conn = get_db_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        UPDATE student_profiles

        SET

            first_name = ?,
            middle_name = ?,
            last_name = ?,
            age = ?,

            student_id = ?,

            phone_number = ?,
            home_address = ?,

            grade_year = ?,
            major_program = ?,

            emergency_name = ?,
            emergency_relationship = ?,
            emergency_phone = ?,
            emergency_email = ?

        WHERE user_id = ?

        """,

        (

            data.get("first_name"),

            data.get("middle_name"),

            data.get("last_name"),

            data.get("age"),


            data.get("student_id"),


            data.get("phone_number"),

            data.get("home_address"),


            data.get("grade_year"),

            normalize_program_name(data.get("major_program")),


            data.get("emergency_name"),

            data.get("emergency_relationship"),

            data.get("emergency_phone"),

            data.get("emergency_email"),


            student_id

        )

    )


    conn.commit()

    conn.close()





def get_student_profile_data(form):

    return {


        "first_name":
            form.get("first_name"),


        "middle_name":
            form.get("middle_name"),


        "last_name":
            form.get("last_name"),


        "age":
            form.get("age"),


        "student_id":
            form.get("student_id"),


        "phone_number":
            form.get("phone_number"),


        "home_address":
            form.get("home_address"),


        "grade_year":
            form.get("grade_year"),


        "major_program":
            normalize_program_name(form.get("major_program")),


        "emergency_name":
            form.get("emergency_name"),


        "emergency_relationship":
            form.get("emergency_relationship"),


        "emergency_phone":
            form.get("emergency_phone"),


        "emergency_email":
            form.get("emergency_email")

    }