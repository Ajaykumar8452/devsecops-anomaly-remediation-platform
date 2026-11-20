FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ALERT_DATABASE_PATH=/app/data/alerts.db

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app

COPY requirements-backend.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade 'pip==26.3' \
    && python -m pip --version \
    && python -m pip install --no-cache-dir -r requirements.txt
RUN set -eu; \
    for spec in 'msgpack>=1.2.3' 'setuptools>=78.1.1' 'urllib3>=2.8.0'; do \
      package="${spec%%[<>=]*}"; \
      if python -c 'import importlib.metadata, sys; importlib.metadata.distribution(sys.argv[1])' "$package" >/dev/null 2>&1; then \
        python -m pip install --no-cache-dir --upgrade "$spec"; \
      else \
        echo "Skipping $package: not installed in the backend dependency set."; \
      fi; \
    done; \
    python -m pip check; \
    python -m pip show msgpack setuptools urllib3 || true; \
    rm -rf \
      /usr/local/lib/python3.13/site-packages/pip \
      /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
      /usr/local/lib/python3.13/ensurepip \
      /usr/local/lib/python3.13/__pycache__/ensurepip* \
      /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13; \
    test ! -e /usr/local/bin/pip \
      && test ! -e /usr/local/bin/pip3 \
      && test ! -e /usr/local/bin/pip3.13 \
      && test ! -e /usr/local/lib/python3.13/ensurepip \
      && test ! -e /usr/local/lib/python3.13/site-packages/pip-26.3.dist-info \
      && \
    python -c 'import importlib.metadata as m, importlib.util as u; assert u.find_spec("pip") is None; assert u.find_spec("ensurepip") is None; assert all(d.metadata["Name"].lower() != "pip" for d in m.distributions())'

COPY --chown=app:app main.py ./main.py
COPY --chown=app:app core/ ./core/
COPY --chown=app:app docker/backend_entrypoint.py ./backend_entrypoint.py

USER 10001:10001

RUN python -c 'import fastapi, uvicorn, psutil, prometheus_client, main; print("backend import smoke passed without pip")'

EXPOSE 8000

ENTRYPOINT ["python", "/app/backend_entrypoint.py"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
