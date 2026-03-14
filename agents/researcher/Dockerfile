FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/researcher/ ./agents/researcher/
COPY shared/ ./shared/
COPY config/ ./config/
COPY scripts/init_db.py ./scripts/init_db.py
COPY scripts/__init__.py ./scripts/__init__.py

CMD ["sh", "-c", "python scripts/init_db.py && python -m agents.researcher.main"]
