FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SCOOBY_DATA=/data
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-dejavu-core && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 scooby && mkdir /data && chown scooby:scooby /data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=scooby:scooby app.py store.py worker.py provider.py case_engine.py case_world.py case_jobs.py case_model.py case_graph.py graph_activity_read.py diagnostic_import.py seed_restore.py ./
COPY --chown=scooby:scooby schemas ./schemas
COPY --chown=scooby:scooby modules/discovery ./modules/discovery
COPY --chown=scooby:scooby modules/investigation ./modules/investigation
COPY --chown=scooby:scooby vendor/reader ./vendor/reader
COPY --chown=scooby:scooby vendor/pdf_export ./vendor/pdf_export
COPY --chown=scooby:scooby ops ./ops
COPY --chown=scooby:scooby publication ./publication
USER scooby
EXPOSE 8000
# Render (and similar hosts) set $PORT; local Compose uses the 8000 default. ops/start.sh optionally seeds
# reports (SCOOBY_SEED_ARCHIVE) and runs the worker in this container (SCOOBY_EMBEDDED_WORKER) before the API.
CMD ["sh", "/app/ops/start.sh"]
