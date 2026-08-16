"""Camera test web app - MJPEG stream + snapshot on port 8000."""
import threading
import time

import cv2
from flask import Flask, Response, jsonify, send_file

DEVICE = "/dev/video0"
WIDTH, HEIGHT, FPS = 640, 480, 30

app = Flask(__name__)


class Camera:
    def __init__(self):
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.ok = False
        self.error = None
        self.started_at = None
        self.frames = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        cap = cv2.VideoCapture(DEVICE)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        return cap if cap.isOpened() else None

    def _loop(self):
        while True:
            if self.cap is None:
                self.cap = self._open()
                if self.cap is None:
                    self.ok, self.error = False, f"cannot open {DEVICE}"
                    time.sleep(2)
                    continue
                self.started_at, self.frames = time.time(), 0
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.cap.release()
                self.cap, self.ok, self.error = None, False, "read failed, reopening"
                time.sleep(1)
                continue
            with self.lock:
                self.frame, self.ok, self.error = frame, True, None
                self.frames += 1

    def jpeg(self):
        with self.lock:
            if self.frame is None:
                return None
            return cv2.imencode(".jpg", self.frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    def info(self):
        fps = self.frames / (time.time() - self.started_at) if self.started_at and self.frames else 0
        return {"ok": self.ok, "device": DEVICE, "error": self.error,
                "resolution": f"{WIDTH}x{HEIGHT}", "avg_fps": round(fps, 1), "frames": self.frames}


cam = Camera()


@app.route("/")
def index():
    return """<!doctype html><html><head><title>Pi Cam Test</title>
<style>body{font-family:sans-serif;background:#111;color:#eee;text-align:center}
img{max-width:90%;border:2px solid #444;border-radius:8px}
a,button{display:inline-block;margin:12px;padding:10px 20px;background:#28a746;color:#fff;
border-radius:6px;text-decoration:none;border:none;font-size:16px;cursor:pointer}
#st{color:#8a8}</style></head><body>
<h2>USB Camera Test</h2><img src="/video" alt="stream"><br>
<a href="/snapshot">Save snapshot</a>
<button onclick="location.reload()">Refresh</button>
<p id="st">loading...</p>
<script>fetch('/health').then(r=>r.json()).then(d=>{
document.getElementById('st').textContent=JSON.stringify(d)})</script>
</body></html>"""


@app.route("/video")
def video():
    def gen():
        while True:
            jpg = cam.jpeg()
            if jpg:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
            time.sleep(1 / FPS)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot")
def snapshot():
    jpg = cam.jpeg()
    if jpg is None:
        return jsonify(cam.info()), 503
    path = "/tmp/snap.jpg"
    with open(path, "wb") as f:
        f.write(jpg)
    return send_file(path, mimetype="image/jpeg", as_attachment=True, download_name="snapshot.jpg")


@app.route("/health")
def health():
    return jsonify(cam.info())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
