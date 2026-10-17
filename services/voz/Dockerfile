# Servidor de voz local (GPU), motor CHATTERBOX: transcrição (faster-whisper) + voz com clonagem (Chatterbox Multilingual, MIT).
# Base com PyTorch 2.7 / CUDA 12.8: necessária para RTX série 50 (Blackwell, ex.: 5070).
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY services/voz/requirements.txt services/voz/requirements-chatterbox.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-chatterbox.txt && pip install --no-cache-dir --no-deps chatterbox-tts==0.1.7
COPY services/voz/app.py .
ENV HF_HOME=/modelos DATA_DIR=/data WHISPER_MODEL=large-v3-turbo ENGINE=chatterbox PRELOAD=0 IDLE_MIN=10
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
