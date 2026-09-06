# Remaining Standalone Page Screenshot Coverage

Captured from the running Nexora application with live CSS and existing SQLite relationships. Navigation was GET-only using signed role sessions; no forms were submitted.

## New screenshots

| Page | Route | Template | Screenshot |
|---|---|---|---|
| Student class detail | `/student/classes/99413` | `classroom/student_class.html` | `screenshots/student/student-class-detail-HD.png` |
| Student classwork | `/student/classes/99413/classwork` | `classroom/student_classwork.html` | `screenshots/student/student-classwork-HD.png` |
| Student classwork detail | `/student/classes/99413/classwork/495` | `classroom/student_classwork_detail.html` | `screenshots/student/student-classwork-detail-HD.png` |
| Student assignment detail | `/student/classes/99413/assignments/495` | `classroom/student_assignment.html` | `screenshots/student/student-assignment-detail-HD.png` |
| Student gradebook | `/student/classes/99413/gradebook` | `classroom/student_gradebook.html` | `screenshots/student/student-gradebook-HD.png` |
| Student performance insights | `/student/classes/99413/performance` | `classroom/student_insights.html` | `screenshots/student/student-performance-insights-HD.png` |
| Student performance report | `/student/classes/99413/reports` | `classroom/student_report.html` | `screenshots/student/student-performance-report-HD.png` |
| Student classmate profile | `/student/classes/100596/people/100778` | `classroom/student_classmate_profile.html` | `screenshots/student/student-classmate-profile-HD.png` |
| Student classmate insights | `/student/classes/100596/people/100778/insights` | `classroom/student_classmate_insights.html` | `screenshots/student/student-classmate-insights-HD.png` |
| Student class information modal | `/student/classes/100596` | `classroom/student_class.html` | `screenshots/student/student-class-information-modal-HD.png` |
| Student profile edit | `/student/profile/edit` | `student/profile_edit.html` | `screenshots/student/student-profile-edit-HD.png` |
| Student profile setup | `/student/profile/setup` | `student/profile_setup.html` | `screenshots/student/student-profile-setup-HD.png` |
| Supervisor assignment detail | `/supervisor/classes/99413/assignments/495` | `classroom/supervisor_assignment.html` | `screenshots/supervisor/supervisor-assignment-detail-HD.png` |
| Supervisor submissions list | `/supervisor/classes/99413/classwork/495/submissions` | `classroom/supervisor_classwork_submissions.html` | `screenshots/supervisor/supervisor-assignment-submissions-HD.png` |
| Supervisor import scores | `/supervisor/classes/99413/classwork/495/import` | `classroom/supervisor_classwork_import.html` | `screenshots/supervisor/supervisor-import-scores-HD.png` |
| Supervisor student report | `/supervisor/classes/99413/reports/99339` | `classroom/supervisor_student_report.html` | `screenshots/supervisor/supervisor-student-report-HD.png` |
| Supervisor task detail | `/supervisor/task/2` | `supervisor/view_task.html` | `screenshots/supervisor/supervisor-task-detail-HD.png` |
| Supervisor edit task | `/supervisor/task/2/edit` | `supervisor/edit_task.html` | `screenshots/supervisor/supervisor-edit-task-HD.png` |
| Admin assignments management | `/admin/assignments` | `admin/assignments.html` | `screenshots/admin/admin-assignments-management-HD.png` |
| Admin student overview | `/admin/reports/student/1/overview` | `admin/reports/student_overview.html` | `screenshots/admin/admin-student-overview-HD.png` |
| Admin dated logbook | `/admin/reports/student/1/logbook/2026-07-14` | `admin/reports/student_logbook.html` | `screenshots/admin/admin-student-logbook-date-HD.png` |

## Remaining standalone pages / unreachable reasons

- `classroom/supervisor_classwork_review.html` — unreachable: `classwork_submissions` has no rows; requires an existing submission ID.
- `classroom/supervisor_submission.html` — unreachable: `classroom_submissions` has no rows; requires an existing submission ID.
- `student/edit_log.html` — unreachable: all existing attendance sessions are closed; the route redirects closed-session logs.
- `auth/reset_password.html` valid-token state — unreachable: no existing password-reset token; invalid-token state is already captured.
- `classroom/student_teacher_profile.html` — not opened: its GET helper executes schema creation/commit and may create a supervisor profile, conflicting with the no-database-modification constraint.

## Exclusions

Reusable components/includes, legacy templates, and templates without an active standalone GET route were excluded.

## Integrity

Application code, HTML, CSS, JavaScript, Python, and database were not modified by this capture.