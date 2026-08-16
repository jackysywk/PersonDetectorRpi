import os

import cv2
import numpy as np
import onnxruntime as ort

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "yolov8n.onnx")
PERSON_CLS = 0


class PersonDetector:
    def __init__(self, conf_threshold=0.45, input_size=640):
        self.conf_threshold = conf_threshold
        self.input_size = input_size
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        self.session = ort.InferenceSession(MODEL_PATH, so, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def _letterbox(self, img):
        h, w = img.shape[:2]
        new = self.input_size
        r = min(new / h, new / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((new, new, 3), 114, dtype=np.uint8)
        top, left = (new - nh) // 2, (new - nw) // 2
        canvas[top:top + nh, left:left + nw] = resized
        return canvas, r, left, top

    def detect(self, frame):
        h, w = frame.shape[:2]
        canvas, r, left, top = self._letterbox(frame)
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1).astype(np.float32) / 255.0
        out = self.session.run(None, {self.input_name: blob[None]})[0][0].T  # (8400, 84)

        scores = out[:, 4:]
        cls_ids = scores.argmax(1)
        confs = scores.max(1)
        mask = (cls_ids == PERSON_CLS) & (confs >= self.conf_threshold)
        if not mask.any():
            return []

        rows = out[mask]
        c = confs[mask]
        xy, wh = rows[:, :2], rows[:, 2:4]
        xy1 = ((xy - wh / 2 - [left, top]) / r).astype(int)
        xy2 = ((xy + wh / 2 - [left, top]) / r).astype(int)
        boxes = np.concatenate([np.clip(xy1, 0, [w, h]), np.clip(xy2, 0, [w, h])], 1)

        keep = cv2.dnn.NMSBoxes(boxes.tolist(), c.tolist(), self.conf_threshold, 0.45)
        idx = np.array(keep).flatten() if len(keep) else []
        return [(int(x1), int(y1), int(x2), int(y2), float(cf))
                for (x1, y1, x2, y2), cf in zip(boxes[idx], c[idx])]
