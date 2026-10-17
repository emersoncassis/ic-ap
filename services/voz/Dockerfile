# Servidor de voz local (GPU): transcrição (faster-whisper) + voz com clonagem (Chatterbox Multilingual, licença MIT).
# Base com PyTorch 2.7 / CUDA 12.8: necessária para RTX série 50 (Blackwell, ex.: 5070).
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY services/voz/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --no-deps chatterbox-tts==0.1.7
COPY services/voz/app.py .
ENV HF_HOME=/modelos DATA_DIR=/data WHISPER_MODEL=large-v3-turbo
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
