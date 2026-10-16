FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
ARG TARGETARCH
ADD https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH} /usr/local/bin/cloudflared
RUN chmod +x /usr/local/bin/cloudflared
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV TEMPLATES_DIR=/srv/card-templates DATA_DIR=/data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
