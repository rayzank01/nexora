FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m -u 10001 nexora
COPY nexora ./nexora
RUN mkdir /app/data && chown -R nexora:nexora /app
USER nexora
ENV PYTHONUNBUFFERED=1 HTTP_HOST=0.0.0.0
EXPOSE 8080
CMD ["python", "-m", "nexora"]
