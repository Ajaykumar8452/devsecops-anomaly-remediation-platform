FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ALERT_DATABASE_PATH=/app/data/alerts.db

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app

COPY requirements-backend.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app main.py ./main.py
COPY --chown=app:app core/ ./core/
COPY --chown=app:app docker/backend_entrypoint.py ./backend_entrypoint.py

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["python", "/app/backend_entrypoint.py"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
