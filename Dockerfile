# Боту нужен только Python: ни браузера, ни драйверов — образ лёгкий, а на
# бесплатном тарифе с 512 МБ это решает.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
