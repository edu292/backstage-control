FROM python:3.13.9-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-deps --no-cache-dir -r requirements.txt

COPY . .

CMD ["granian", "--interface", "wsgi", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--backpressure", "7", "backstage_control.wsgi:application"]