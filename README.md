# ACU AI Chatbot

Backend for the Acıbadem University AI chatbot: Django 5.x, PostgreSQL 16, and (in later phases) responsible public scraping from the main site and Bologna pages.

## Requirements

- Docker and Docker Compose

## Run the stack

From the repository root:

```bash
docker compose up --build
```

- **Web:** http://localhost:8000 (host and container both use port 8000). Admin: `/admin/` after you create a superuser.
- **Database:** PostgreSQL is reachable from the host on port `5433` by default (`POSTGRES_PUBLISH_PORT`; inside Compose the hostname is `db` on port `5432`).

On first start the `web` service runs migrations, then starts Gunicorn.

### Environment

Copy `.env.example` to `.env` and adjust values. Compose substitutes variables from `.env` when present.

### Create an admin user

```bash
docker compose exec web python manage.py createsuperuser
```

Open the admin UI at http://localhost:8000/admin/ (or your host if you override networking).

## Project layout

- `docker-compose.yml` — `web` (Django) and `db` (PostgreSQL 15+).
- `.env.example` — environment template.
- `webapp/` — Django project (`config`, `chat`, `scraper`, templates, static).
