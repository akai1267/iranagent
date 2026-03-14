FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/source_monitor/ ./agents/source_monitor/
COPY shared/ ./shared/
COPY config/ ./config/

CMD ["python", "-m", "agents.source_monitor.main"]
