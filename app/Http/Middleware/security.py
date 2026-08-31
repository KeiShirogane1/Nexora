from functools import wraps
from flask import session, redirect

def role_required(role):

    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):

            if "user_id" not in session:
                return redirect("/login")

            if session.get("role") != role:
                return "Unauthorized Access", 403

            return func(*args, **kwargs)

        return inner

    return wrapper

def login_required(func):
    @wraps(func)
    def inner(*args, **kwargs):

        if "user_id" not in session:
            return redirect("/login")

        return func(*args, **kwargs)

    return inner

