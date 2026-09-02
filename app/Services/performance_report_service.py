"""Thesis-ready performance report service."""
from app.Models.db import get_db_connection
from app.Services.classwork_ml_service import build_student_ml_analysis
from app.Services.ml_recommendation_service import build_recommendation_from_features


def _value(row,key,index=0,default=None):
    if row is None:return default
    try:
        if key in row.keys():return row[key]
    except AttributeError:pass
    try:return row[index]
    except (IndexError,KeyError,TypeError):return default


def _get_latest_feedback_text(student_id):
    conn=get_db_connection()
    try:
        try:
            fb=conn.execute("SELECT comment FROM feedback WHERE student_id=? ORDER BY created_at DESC LIMIT 1",(student_id,)).fetchone()
            if fb and _value(fb,"comment",0):return str(_value(fb,"comment",0)).strip()
        except Exception:pass
        try:
            sub=conn.execute("SELECT feedback FROM classroom_submissions WHERE student_id=? AND feedback IS NOT NULL AND TRIM(feedback)!='' ORDER BY submitted_at DESC LIMIT 1",(student_id,)).fetchone()
            if sub and _value(sub,"feedback",0):return str(_value(sub,"feedback",0)).strip()
        except Exception:pass
    finally:conn.close()
    return ""


def _safe_float(v,default=None):
    try:
        if v is None:return default
        f=float(v)
        return default if f!=f or f in (float("inf"),float("-inf")) else f
    except Exception:return default


def build_student_report(student_id,class_id,feedback_text=None):
    if feedback_text is None:feedback_text=_get_latest_feedback_text(student_id)
    feedback_text=feedback_text or ""
    try:
        analysis=build_student_ml_analysis(student_id,class_id,feedback_text=feedback_text)
    except Exception:
        from app.ML.predictor import analyze_feedback_detailed
        from app.Services.classwork_ml_service import build_student_performance_features,classify_numeric_performance
        features=build_student_performance_features(student_id,class_id)
        fa=analyze_feedback_detailed(feedback_text); label=classify_numeric_performance(features.get("average_percentage"))
        analysis={"student_id":student_id,"class_id":class_id,"features":features,"numeric_performance_label":label,"performance_label":label,"feedback_analysis":fa}

    features=analysis.get("features") or {}; feedback_analysis=analysis.get("feedback_analysis") or {}
    numeric_label=analysis.get("numeric_performance_label") or analysis.get("performance_label") or "Satisfactory"
    try: ml_reco=build_recommendation_from_features(features,feedback_analysis,performance_label=numeric_label)
    except Exception: ml_reco={"performance_label":numeric_label,"overall_percentage":_safe_float(features.get("average_percentage")),"completion_rate":_safe_float(features.get("completion_rate"),0.0) or 0.0,"recommendation":feedback_analysis.get("recommendation","Continue monitoring performance."),"priority":"medium","basis":[]}

    student={"id":student_id,"username":"Student","email":"","student_number":""}; class_info={"id":class_id,"name":"Class","section":"","code":""}; supervisor_info={"id":None,"username":"","email":""}; assignments=[]; strongest=None; weakest=None
    conn=get_db_connection()
    try:
        row=conn.execute("SELECT u.id,u.username,u.email,COALESCE(p.student_id,'') AS student_number FROM users u LEFT JOIN student_profiles p ON p.user_id=u.id WHERE u.id=?",(student_id,)).fetchone()
        if row:student={"id":_value(row,"id",0,student_id),"username":_value(row,"username",1,"Student"),"email":_value(row,"email",2,""),"student_number":_value(row,"student_number",3,"")}
        crow=conn.execute("SELECT c.id,c.name,c.section,c.code,c.supervisor_id,u.username AS sup_name,u.email AS sup_email FROM classrooms c LEFT JOIN users u ON u.id=c.supervisor_id WHERE c.id=?",(class_id,)).fetchone()
        if crow:
            class_info={"id":_value(crow,"id",0,class_id),"name":_value(crow,"name",1,"Class"),"section":_value(crow,"section",2,""),"code":_value(crow,"code",3,""),"supervisor_id":_value(crow,"supervisor_id",4)}
            supervisor_info={"id":_value(crow,"supervisor_id",4),"username":_value(crow,"sup_name",5,""),"email":_value(crow,"sup_email",6,"")}
        rows=conn.execute("""SELECT a.id,a.title,a.points,s.score,s.max_score,s.percentage,s.grading_method,
               (SELECT cs.grade FROM classwork_submissions cs WHERE cs.assignment_id=a.id AND cs.student_id=? AND cs.grade IS NOT NULL ORDER BY cs.attempt_no DESC,cs.id DESC LIMIT 1) AS submission_grade
               FROM classroom_assignments a LEFT JOIN classwork_scores s ON s.assignment_id=a.id AND s.student_id=?
               WHERE a.classroom_id=? ORDER BY a.created_at ASC,a.id ASC""",(student_id,student_id,class_id)).fetchall()
        for r in rows:
            title=_value(r,"title",1,"Assignment"); points=_safe_float(_value(r,"points",2),0) or 0; score=_value(r,"score",3); max_score=_value(r,"max_score",4); pct=_value(r,"percentage",5); method=_value(r,"grading_method",6); sub_grade=_value(r,"submission_grade",7)
            if score is None and sub_grade is not None:score=float(sub_grade); max_score=points; pct=(score/max_score*100) if max_score else 0; method=method or "manual"
            if score is None or max_score is None or _safe_float(max_score,0)<=0:
                assignments.append({"title":title,"points":points,"score":None,"max_score":_safe_float(max_score,points),"percentage":None,"grading_method":None,"graded":False}); continue
            pct_f=_safe_float(pct)
            if pct_f is None:pct_f=float(score)/float(max_score)*100
            assignments.append({"title":title,"points":points,"score":_safe_float(score),"max_score":_safe_float(max_score),"percentage":pct_f,"grading_method":method,"graded":True})
        graded_only=[a for a in assignments if a["graded"] and a["percentage"] is not None]
        if graded_only:strongest=max(graded_only,key=lambda x:x["percentage"]); weakest=min(graded_only,key=lambda x:x["percentage"])
    finally:conn.close()

    has_feedback=not bool(feedback_analysis.get("is_empty",True)) if isinstance(feedback_analysis,dict) else False
    return {"student":student,"class":class_info,"supervisor":supervisor_info,"overall_percentage":_safe_float(features.get("average_percentage")),"completion_rate":_safe_float(features.get("completion_rate"),0.0) or 0.0,"graded_count":features.get("graded_count",0),"total_count":features.get("total_count",0),"performance_label":numeric_label,"performance_classification":numeric_label,"feedback_analysis":feedback_analysis if has_feedback else None,"sentiment":feedback_analysis.get("sentiment") if has_feedback else None,"competency":feedback_analysis.get("competency"),"has_feedback":has_feedback,"ml_recommendation":ml_reco,"recommendation":ml_reco.get("recommendation"),"priority":ml_reco.get("priority"),"basis":ml_reco.get("basis",[]),"strongest":strongest,"weakest":weakest,"assignments":assignments,"average_percentage":_safe_float(features.get("average_percentage")),"min_percentage":_safe_float(features.get("min_percentage")),"max_percentage":_safe_float(features.get("max_percentage")),"manual_count":features.get("manual_count",0),"imported_count":features.get("imported_count",0)}


def build_class_reports(class_id):
    conn=get_db_connection()
    try:student_ids=[_value(r,"student_id",0) for r in conn.execute("SELECT student_id FROM classroom_students WHERE classroom_id=? ORDER BY student_id",(class_id,)).fetchall()]
    finally:conn.close()
    return [build_student_report(int(sid),class_id) for sid in student_ids]
