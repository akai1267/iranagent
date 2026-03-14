FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agents/ ./agents/
COPY api/ ./api/
COPY shared/ ./shared/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY start_all.sh ./start_all.sh
COPY --from=frontend-build /frontend/dist ./frontend/dist

RUN chmod +x ./start_all.sh

CMD ["./start_all.sh"]
