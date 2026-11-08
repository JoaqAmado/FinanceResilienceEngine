FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY sql/ sql/
COPY tests/ tests/
COPY app/ app/
ENV PYTHONPATH=/app/src:/app \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg
