from app.Models.db import get_db_connection



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

            data.get("major_program"),


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
            form.get("major_program"),


        "emergency_name":
            form.get("emergency_name"),


        "emergency_relationship":
            form.get("emergency_relationship"),


        "emergency_phone":
            form.get("emergency_phone"),


        "emergency_email":
            form.get("emergency_email")

    }