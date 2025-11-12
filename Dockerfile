FROM python:3.14.0-slim-trixie AS base

LABEL org.opencontainers.image.source=https://github.com/edu292/backstage-control

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-deps --no-cache-dir -r requirements.txt

COPY src .

FROM base AS builder

COPY compress-and-minify-staticfiles.sh .

RUN chmod +x compress-and-minify-staticfiles.sh && \
    apt-get update && apt-get install -y \
    curl \
    brotli \
    gzip

RUN curl -fsSL https://esbuild.github.io/dl/v0.25.12 | sh

COPY static ./static
RUN python manage.py collectstatic --no-input

RUN ./compress-and-minify-staticfiles.sh

FROM base AS final

COPY --from=builder /app/staticfiles ./temp_staticfiles

CMD ["granian", "--interface", "wsgi", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--backpressure", "7", "backstage_control.wsgi:application"]