FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    swig gcc curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py detector.py alarm.py ./
RUN mkdir -p models \
    && curl -sL -o models/yolov8n.onnx https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.onnx

EXPOSE 8000

CMD ["python", "main.py"]
