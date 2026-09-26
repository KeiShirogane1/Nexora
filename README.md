# Nexora

Internship performance and classroom platform with ML-informed feedback analysis.

## Local Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill values
python -m pytest -q
python run.py  # http://127.0.0.1:5000
# or gunicorn bootstrap.app:app
```

Database is initialized on first import via `scripts/init_db.py`. Default is SQLite `nexora.db`; set `DATABASE_URL` for PostgreSQL.

## Validation

The authoritative automated test suite lives in `system_validation/`. Root-level pytest discovery is configured through `pytest.ini`, so either of these commands runs the same project validation suite:

```bash
python -m pytest -q
python -m pytest system_validation -q
```

Do not use `pytest tests/` for this repository; Nexora intentionally keeps its validation suite in `system_validation/`.

## Required Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | production | Flask session secret (generate random string) |
| `DATABASE_URL` | production (Railway) | PostgreSQL URL, e.g. `postgresql://user:pass@host/db`. If unset, falls back to `nexora.db` SQLite |
| `BREVO_API_KEY` | for email | Brevo SMTP API key |
| `BREVO_SENDER_EMAIL` | for email | Verified sender email for Brevo |
| `BREVO_SENDER_NAME` | optional | Sender name, default `Nexora` |
| `APP_BASE_URL` | recommended | Public base URL for password-reset links, e.g. your Railway service domain |
| `FLASK_ENV` | Railway | Set `production` in Railway (enables secure cookies, requires `SECRET_KEY`) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | optional | Initial admin provisioning (min 12 chars) |

See `.env.example` for template. Never commit `.env`.

## Railway Deployment

Railway deploys Nexora from the root `Dockerfile`, which installs `requirements.txt` and starts Gunicorn on Railway's `PORT`. The service health check is `/health`.

Required Railway env vars: `SECRET_KEY`, `DATABASE_URL`, `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, and `APP_BASE_URL`. Configure `ADMIN_USERNAME`/`ADMIN_PASSWORD` only when initial admin provisioning is needed.

## ML Model Files

Required for production (already committed):

- `app/ML/model/vectorizer.pkl`
- `app/ML/model/performance_model.pkl`
- `app/ML/model/svm_model.pkl` (optional, used if present)
- `app/ML/dataset/feedback_dataset.csv`

These are tracked in git (not ignored). Do not delete. Missing files are handled gracefully by `app/ML/predictor.py` (fallback to `Satisfactory` with `confidence 0.0`). Do not retrain without updating `metrics.json`.

## Brevo Email

Configuration is via `BREVO_API_KEY` and `BREVO_SENDER_EMAIL` from environment. Hardcoded secrets are not used. Missing keys raise `RuntimeError` only when sending email, not on startup. Verify in production logs that no secret is printed.

## Security Notes

- Auth via `app/Http/Middleware/security.py:role_required` + `login_required`
- Supervisor ownership checks on all `/supervisor/classes/<id>/*` routes
- Student IDOR protection: `/student/classes/<id>/*` uses `session["user_id"]` only, never `student_id` URL param
- Class membership checks on all report/gradebook/insights routes
- `WTF_CSRF_ENABLED` true by default, secure cookies in production
- `SECRET_KEY` must be set in production
