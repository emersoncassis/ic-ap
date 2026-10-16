FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV TEMPLATES_DIR=/srv/card-templates DATA_DIR=/data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
