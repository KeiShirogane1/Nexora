from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.Http.Middleware.security import role_required
from app.Services.account_appeal_service import (
    APPEAL_WINDOW_HOURS,
    approve_account_appeal,
    authenticate_appeal_account,
    deny_account_appeal,
    get_account_case,
    get_admin_appeal_cases,
    process_expired_account_cases,
    submit_account_appeal,
)

account_appeals=Blueprint("account_appeals",__name__)


@account_appeals.route("/account/appeal")
def appeal_portal():
    try: process_expired_account_cases()
    except Exception: pass
    user_id=session.get("appeal_user_id")
    case=get_account_case(user_id) if user_id else None
    if user_id and not case: session.pop("appeal_user_id",None)
    return render_template("auth/account_appeal.html",case=case,appeal_window_hours=APPEAL_WINDOW_HOURS)


@account_appeals.route("/account/appeal/verify",methods=["POST"])
def appeal_verify():
    case,error=authenticate_appeal_account(request.form.get("identifier"),request.form.get("password"))
    if error:
        flash(error,"danger")
        return redirect(url_for("account_appeals.appeal_portal"))
    session["appeal_user_id"]=int(case["user_id"])
    flash("Account verified. You may now submit your appeal.","success")
    return redirect(url_for("account_appeals.appeal_portal"))


@account_appeals.route("/account/appeal/submit",methods=["POST"])
def appeal_submit():
    user_id=session.get("appeal_user_id")
    if not user_id:
        flash("Verify your inactive account first.","danger")
        return redirect(url_for("account_appeals.appeal_portal"))
    case,error=submit_account_appeal(int(user_id),request.form.get("reason"))
    if error:
        flash(error,"danger")
    else:
        flash("Appeal submitted. Permanent removal is paused while the administrator reviews your request.","success")
    return redirect(url_for("account_appeals.appeal_portal"))


@account_appeals.route("/account/appeal/exit",methods=["POST"])
def appeal_exit():
    session.pop("appeal_user_id",None)
    return redirect(url_for("auth.login"))


@account_appeals.route("/admin/appeals")
@role_required("admin")
def admin_appeals():
    cases=get_admin_appeal_cases()
    submitted=[c for c in cases if c["appeal_status"]=="submitted"]
    awaiting=[c for c in cases if c["appeal_status"]=="eligible"]
    expiring=[c for c in awaiting if c["remaining_seconds"]<=6*60*60]
    return render_template(
        "admin/appeals.html",active_page="appeals",appeal_cases=cases,
        submitted_count=len(submitted),awaiting_count=len(awaiting),
        expiring_count=len(expiring),highlight_case_id=request.args.get("case",type=int),
        appeal_window_hours=APPEAL_WINDOW_HOURS,
    )


@account_appeals.route("/admin/appeals/<int:case_id>/approve",methods=["POST"])
@role_required("admin")
def admin_appeal_approve(case_id):
    case=approve_account_appeal(case_id,int(session["user_id"]))
    flash(
        f"{case['username']}'s appeal was approved and the account was reactivated." if case else "That appeal is no longer available.",
        "success" if case else "warning",
    )
    return redirect(url_for("account_appeals.admin_appeals"))


@account_appeals.route("/admin/appeals/<int:case_id>/deny",methods=["POST"])
@role_required("admin")
def admin_appeal_deny(case_id):
    case=deny_account_appeal(case_id,int(session["user_id"]))
    flash(
        f"{case['username']}'s appeal was denied and the account identity was permanently removed." if case else "That appeal is no longer available.",
        "success" if case else "warning",
    )
    return redirect(url_for("account_appeals.admin_appeals"))
