import atexit
import os
import signal
import sys
import threading
import time

import cv2
from flask import Flask, Response, jsonify, send_file

from alarm import AlarmController
from detector import PersonDetector

DEVICE = os.environ.get("CAM_DEVICE", "/dev/video0")
BUZZER_PIN = int(os.environ.get("BUZZER_PIN", "17"))
CONF = float(os.environ.get("CONF_THRESHOLD", "0.5"))
GRACE = float(os.environ.get("START_GRACE", "5"))
WIDTH, HEIGHT, FPS = 640, 480, 30

app = Flask(__name__)
alarm = AlarmController(pin=BUZZER_PIN)
atexit.register(alarm.close)


def _shutdown(signum, frame):
    alarm.silence()
    alarm.close()
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)

try:
    detector = PersonDetector(conf_threshold=CONF)
    detector_err = None
except Exception as e:
    detector = None
    detector_err = str(e)

state = {"cam_ok": False, "cam_error": None, "frames": 0, "det_fps": 0.0,
         "person": False, "conf": 0.0, "boxes": [], "start": time.time(),
         "alarms": 0}
lock = threading.Lock()
latest = {"frame": None}


def camera_loop():
    cap = None
    while True:
        if cap is None:
            cap = cv2.VideoCapture(DEVICE)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, FPS)
            if not cap.isOpened():
                with lock:
                    state["cam_ok"], state["cam_error"] = False, f"cannot open {DEVICE}"
                cap = None
                time.sleep(2)
                continue
            with lock:
                state["cam_ok"], state["cam_error"], state["frames"] = True, None, 0
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            cap = None
            with lock:
                state["cam_ok"], state["cam_error"] = False, "read failed, reopening"
            time.sleep(1)
            continue
        with lock:
            latest["frame"] = frame
            state["frames"] += 1


def detection_loop():
    det_start, det_frames = time.time(), 0
    while True:
        with lock:
            frame = None if latest["frame"] is None else latest["frame"].copy()
        if frame is not None and detector is not None:
            det_error = None
            try:
                boxes = detector.detect(frame)
            except Exception as e:
                boxes = []
                det_error = str(e)
            det_frames += 1
            person = bool(boxes)
            armed = time.time() - state["start"] > GRACE
            if alarm.set_active(person and armed):
                with lock:
                    state["alarms"] += 1
            conf = max((b[4] for b in boxes), default=0.0)
            with lock:
                state["boxes"], state["person"], state["conf"] = boxes, person, conf
                state["det_fps"] = round(det_frames / (time.time() - det_start), 1)
                if det_error:
                    state["det_error"] = det_error
                else:
                    state.pop("det_error", None)
        else:
            alarm.set_active(False)
            with lock:
                state["person"], state["boxes"] = False, []
        time.sleep(0.05)


def startup_jingle():
    t0 = time.time()
    cam_ok = False
    while time.time() - t0 < 30:
        with lock:
            cam_ok = state["cam_ok"]
        if cam_ok and detector is not None and alarm.ok:
            break
        time.sleep(0.5)
    with lock:
        cam_ok = state["cam_ok"]
    if cam_ok and detector is not None and alarm.ok:
        alarm.startup_ok()
    else:
        alarm.startup_fail()


def annotated_jpeg():
    with lock:
        frame = None if latest["frame"] is None else latest["frame"].copy()
        boxes, person, conf = state["boxes"], state["person"], state["conf"]
    if frame is None:
        return None
    for x1, y1, x2, y2, c in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(frame, f"PERSON {c:.0%}", (x1, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    label = f"PERSON {conf:.0%}" if person else "CLEAR"
    color = (0, 0, 255) if person else (0, 255, 0)
    cv2.putText(frame, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


threading.Thread(target=camera_loop, daemon=True).start()
threading.Thread(target=detection_loop, daemon=True).start()
threading.Thread(target=startup_jingle, daemon=True).start()

PAGE = """<!doctype html><html><head><title>Pi Human Detector</title>
<style>body{font-family:sans-serif;background:#111;color:#eee;text-align:center}
img{max-width:92%;border:2px solid #444;border-radius:8px}
button,a.b{display:inline-block;margin:10px;padding:10px 18px;color:#fff;border:none;
border-radius:6px;font-size:15px;cursor:pointer;text-decoration:none}
.on{background:#c0392b}.off{background:#2c3e50}.b{background:#28a746}
#st{font-family:monospace;color:#8a8;font-size:14px}</style></head><body>
<h2>Human Detector</h2><img src="/video" alt="stream"><br>
<button class="b" onclick="fetch('/api/beep',{method:'POST'})">Test beep</button>
<button id="al" class="on" onclick="toggle()">Alarm: ON</button>
<a class="b" href="/snapshot">Snapshot</a>
<p id="st">loading...</p>
<script>
function toggle(){fetch('/api/alarm',{method:'POST'}).then(r=>r.json()).then(d=>setb(d.enabled))}
function setb(on){const b=document.getElementById('al');b.textContent='Alarm: '+(on?'ON':'OFF');
b.className=on?'on':'off'}
fetch('/health').then(r=>r.json()).then(d=>{setb(d.alarm.enabled);
document.getElementById('st').textContent=JSON.stringify(d.status)})
setInterval(()=>fetch('/health').then(r=>r.json()).then(d=>
document.getElementById('st').textContent=JSON.stringify(d.status)),1000)
</script></body></html>"""


@app.route("/")
def index():
    return PAGE


@app.route("/video")
def video():
    def gen():
        while True:
            jpg = annotated_jpeg()
            if jpg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            time.sleep(1 / FPS)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot")
def snapshot():
    jpg = annotated_jpeg()
    if jpg is None:
        return jsonify({"error": "no frame"}), 503
    path = "/tmp/snap.jpg"
    with open(path, "wb") as f:
        f.write(jpg)
    return send_file(path, mimetype="image/jpeg", as_attachment=True, download_name="snapshot.jpg")


@app.route("/health")
def health():
    with lock:
        st = {"person": state["person"], "conf": round(state["conf"], 2),
              "cam": {"ok": state["cam_ok"], "error": state["cam_error"],
                      "frames": state["frames"]},
              "detector": {"ok": detector is not None,
                           "error": detector_err or state.get("det_error"),
                           "fps": state["det_fps"]},
              "alarms": state["alarms"]}
    return jsonify({"status": st, "alarm": alarm.status()})


@app.route("/api/beep", methods=["POST"])
def api_beep():
    alarm.beep()
    return jsonify({"beep": True})


@app.route("/api/alarm", methods=["POST"])
def api_alarm():
    alarm.enabled = not alarm.enabled
    if not alarm.enabled:
        alarm.silence()
    return jsonify({"enabled": alarm.enabled})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
