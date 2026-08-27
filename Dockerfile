FROM python:3.12-slim

# Nur das Nötigste. curl steckt im Image, weil der Healthcheck es braucht.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/openverba

# Abhängigkeiten zuerst — die ändern sich seltener als der Code, das spart Rebuilds.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
COPY app/ ./app/

# Kein root im laufenden Betrieb.
RUN useradd --system --create-home --uid 1000 openverba \
    && chown -R openverba:openverba /srv/openverba
USER openverba

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
