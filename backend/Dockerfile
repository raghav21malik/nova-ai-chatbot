FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY --from=builder /install /usr/local
WORKDIR /app
COPY app ./app
RUN mkdir -p /data && chown -R 10001:10001 /data /app
USER root
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
