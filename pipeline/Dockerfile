FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install --no-cache-dir -r /app/pipeline/requirements.txt
COPY scripts /app/scripts
COPY pipeline /app/pipeline
ENTRYPOINT ["python", "/app/pipeline/run_job.py"]
