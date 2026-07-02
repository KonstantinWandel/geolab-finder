FROM python:3.11-slim

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/home

RUN useradd --create-home --uid 10011 appuser

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
COPY backend/app/__init__.py /app/app/__init__.py
COPY backend/app/main.py /app/app/main.py
COPY backend/app/services /app/app/services

RUN python -m pip install --upgrade pip && \
    python -m pip install \
      --index-url ${TORCH_INDEX_URL} \
      "torch==2.6.0" && \
    python -m pip install -r /app/requirements.txt \
      "pandas>=2.2,<3" \
      "accelerate>=1.0,<2" \
      "bitsandbytes>=0.45,<0.47" \
      "transformers==4.52.4" \
      "sentencepiece>=0.2,<0.3"

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
