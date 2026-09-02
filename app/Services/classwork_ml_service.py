"""Build ML-ready student performance features and analysis inputs."""

from app.Models.db import get_db_connection
from app.ML.predictor import analyze_feedback_detailed


def _value(row, key, index=0, default=None):
    try:
        if key in row.keys(): return row[key]
    except AttributeError: pass
    try: return row[index]
    except (IndexError, KeyError, TypeError): return default


def build_student_performance_features(student_id, class_id):
    """Return normalized gradebook features, including grades stored on submissions."""
    conn=get_db_connection()
    try:
        total_row=conn.execute("SELECT COUNT(*) AS total_assignments FROM classroom_assignments WHERE classroom_id=?",(class_id,)).fetchone()
        total_assignments=int(_value(total_row,"total_assignments",0,0) or 0)
        rows=conn.execute("""SELECT a.id,
               s.score, s.max_score, s.percentage, s.grading_method,
               (SELECT cs.grade FROM classwork_submissions cs WHERE cs.assignment_id=a.id AND cs.student_id=? AND cs.grade IS NOT NULL ORDER BY cs.attempt_no DESC, cs.id DESC LIMIT 1) AS submission_grade
            FROM classroom_assignments a
            LEFT JOIN classwork_scores s ON s.assignment_id=a.id AND s.student_id=?
            WHERE a.classroom_id=? ORDER BY a.created_at ASC,a.id ASC""",(student_id,student_id,class_id)).fetchall()
    finally: conn.close()

    graded=[]; methods=[]
    for row in rows:
        score=_value(row,"score",1); max_score=_value(row,"max_score",2); percentage=_value(row,"percentage",3); method=_value(row,"grading_method",4)
        submission_grade=_value(row,"submission_grade",5)
        if score is None and submission_grade is not None:
            score=float(submission_grade); max_score=max_score or None
        if score is None: continue
        if max_score is None: continue
        try:
            max_score=float(max_score)
            if max_score<=0: continue
            score=float(score)
            pct=float(percentage) if percentage is not None else score/max_score*100
        except (TypeError,ValueError): continue
        graded.append({"score":score,"max_score":max_score,"percentage":pct})
        methods.append((method or "manual").lower())

    if not graded:
        return {"student_id":student_id,"class_id":class_id,"graded_count":0,"total_count":total_assignments,"average_percentage":None,"min_percentage":None,"max_percentage":None,"completion_rate":0.0,"manual_count":0,"imported_count":0}
    percentages=[x["percentage"] for x in graded]
    return {"student_id":student_id,"class_id":class_id,"graded_count":len(graded),"total_count":total_assignments,"average_percentage":sum(percentages)/len(percentages),"min_percentage":min(percentages),"max_percentage":max(percentages),"completion_rate":len(graded)/total_assignments*100 if total_assignments else 0.0,"manual_count":sum(1 for m in methods if m=="manual"),"imported_count":sum(1 for m in methods if m=="imported")}


def classify_numeric_performance(average_percentage):
    if average_percentage is None: return "Satisfactory"
    score=float(average_percentage)
    if score>=90:return "Excellent"
    if score>=85:return "Very Satisfactory"
    if score>=75:return "Satisfactory"
    if score>=60:return "Fair"
    return "Needs Improvement"


def build_student_ml_analysis(student_id,class_id,feedback_text=""):
    features=build_student_performance_features(student_id,class_id)
    numeric_label=classify_numeric_performance(features["average_percentage"])
    feedback_analysis=analyze_feedback_detailed(feedback_text)
    return {"student_id":student_id,"class_id":class_id,"features":features,"numeric_performance_label":numeric_label,"feedback_analysis":feedback_analysis,"performance_label":numeric_label,"sentiment":feedback_analysis["sentiment"],"competency":feedback_analysis["competency"],"recommendation":feedback_analysis["recommendation"],"confidence":feedback_analysis["confidence"]}
