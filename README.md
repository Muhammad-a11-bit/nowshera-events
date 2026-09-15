# Nowshera Events Co. — COMPLETE Project

This package contains **both FastAPI and n8n**.

## Included

```text
index.html
admin.html

api/
  __init__.py
  index.py                 <-- Python FastAPI backend

n8n/
  nowshera-events-workflow.json

requirements.txt
.env.example
run.bat
run.sh
```

## FastAPI endpoints

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/signup`
- `POST /api/auth/logout`
- `GET /api/auth/session`
- `GET /api/events/upcoming`
- `GET /api/registrations/me`
- `POST /api/events/{event_id}/register`
- `POST /api/registrations/{registration_id}/cancel`
- `GET /api/admin/stats`
- `GET /api/admin/events`
- `POST /api/admin/events`
- `PATCH /api/admin/events/{event_id}`
- `GET /api/admin/events/{event_id}/attendees`
- `GET /api/admin/reports/summary`

Swagger is available at `/docs`.

## Run on Windows

1. Rename `.env.example` to `.env`.
2. Put your Supabase URL and publishable key in `.env`.
3. Run `run.bat`.

Then open:

- Website: `http://127.0.0.1:8000`
- Admin: `http://127.0.0.1:8000/admin`
- FastAPI Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/health`

## n8n

Import:

`n8n/nowshera-events-workflow.json`

into n8n using **Import from File**.

The n8n workflow contains the registration and cancellation automation.
