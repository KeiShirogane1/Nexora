from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)


HASH_PREFIXES = (
    "scrypt:",
    "pbkdf2:",
)


def hash_password(password):
    if not password:
        raise ValueError("Password cannot be empty.")

    return generate_password_hash(
        password,
        method="scrypt"
    )


def is_password_hash(value):
    if not isinstance(value, str):
        return False

    return (
        value.startswith(HASH_PREFIXES)
        and "$" in value
    )


def verify_password(stored_password, submitted_password):
    if not stored_password or not submitted_password:
        return False

    # Plaintext passwords are no longer accepted.
    if not is_password_hash(stored_password):
        return False

    try:
        return check_password_hash(
            stored_password,
            submitted_password
        )

    except (ValueError, TypeError):
        return False