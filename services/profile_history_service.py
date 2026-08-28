from database.db import get_db_connection



def log_profile_change(
    student_id,
    changed_by,
    action
):

    conn = get_db_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        INSERT INTO profile_history
        (
            student_id,
            changed_by,
            action
        )

        VALUES (?, ?, ?)

        """,

        (
            student_id,
            changed_by,
            action
        )
    )


    conn.commit()

    conn.close()





def get_profile_history(student_id):

    conn = get_db_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            profile_history.action,
            profile_history.created_at,
            users.username

        FROM profile_history

        LEFT JOIN users

        ON profile_history.changed_by = users.id


        WHERE profile_history.student_id = ?


        ORDER BY profile_history.created_at DESC

        """,
        (
            student_id,
        )
    )


    history = cursor.fetchall()


    conn.close()


    return history