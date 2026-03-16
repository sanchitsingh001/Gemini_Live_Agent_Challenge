# Build from Narrative_Engine root: docker build -f cloud_run_agent/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY cloud_run_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY gemini_client.py /app/gemini_client.py
COPY cloud_run_agent/main.py /app/main.py
ENV PYTHONPATH=/app
ENV PORT=8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
