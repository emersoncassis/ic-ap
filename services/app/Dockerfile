# Contexto de build = raiz do repositório (docker-compose.yml). Nada é montado do Windows: tudo vai na imagem
# e o único estado (banco, chave, mídia) fica no volume nomeado "data".
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
ADD https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${TARGETARCH} /usr/local/bin/cloudflared
RUN chmod +x /usr/local/bin/cloudflared
WORKDIR /srv
COPY services/app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/app/app ./app
COPY templates /srv/card-templates
COPY skills /srv/skills
COPY context /context
COPY config /config
ENV TEMPLATES_DIR=/srv/card-templates DATA_DIR=/data SKILLS_DIR=/srv/skills
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
