import gc
gc.disable()

import os
import ncnn
import cv2
import numpy as np
import time
import asyncio
import threading
import websockets
from picamera2 import Picamera2

script_dir = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(script_dir, "my_model_ncnn_model")
param_file = os.path.join(model_dir, "model.ncnn.param")
bin_file   = os.path.join(model_dir, "model.ncnn.bin")

input_size  = 640
conf_thresh = 0.5
nms_thresh  = 0.45

labels = [
    "Applicator white/bleu",
    "Applicator white/gray",
    "Applicator gray",
    "Applicator Orange /white",
    "Applicator pink",
    "Inhaler bleu",
    "Inhaler white",
    "Canister"
]

bbox_colors = [
    (173, 216, 230),
    (211, 211, 211),
    (105, 105, 105),
    (255, 165, 0),
    (255, 192, 203),
    (0, 0, 128),
    (255, 255, 255),
    (255, 0, 0)
]

num_classes = len(labels)

net = ncnn.Net()
net.opt.use_vulkan_compute  = False
net.opt.num_threads         = 4
net.opt.use_fp16_packed     = True
net.opt.use_fp16_storage    = True
net.opt.use_fp16_arithmetic = True
net.opt.use_packing_layout  = True

if net.load_param(param_file) != 0:
    raise RuntimeError(f"Failed to load param: {param_file}")
if net.load_model(bin_file) != 0:
    raise RuntimeError(f"Failed to load model: {bin_file}")

print("Model loaded OK")

picam = Picamera2()
picam.configure(picam.create_video_configuration(main={"size": (640, 480)}))
picam.start()
print("Camera OK")

# --- Shared frame buffer ---
latest_frame = None
frame_lock = threading.Lock()

def nms(boxes, scores, threshold):
    if len(boxes) == 0:
        return []
    boxes  = np.array(boxes,  dtype=np.float32)
    scores = np.array(scores, dtype=np.float32)
    x1 = boxes[:, 0]; y1 = boxes[:, 1]
    x2 = boxes[:, 2]; y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep  = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w   = np.maximum(0.0, xx2 - xx1)
        h   = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr   = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[np.where(ovr <= threshold)[0] + 1]
    return keep

# --- WebSocket server ---
connected_clients = set()

async def stream_handler(websocket):
    global latest_frame
    connected_clients.add(websocket)
    print(f"Client connected: {websocket.remote_address}")
    try:
        while True:
            with frame_lock:
                frame = latest_frame
            if frame is not None:
                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                await websocket.send(buf.tobytes())
            await asyncio.sleep(0.03)  # ~30fps max
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    finally:
        connected_clients.discard(websocket)

async def run_server():
    print("WebSocket server started on ws://0.0.0.0:8765")
    async with websockets.serve(stream_handler, "0.0.0.0", 8765):
        await asyncio.Future()

def start_server():
    asyncio.run(run_server())

# Start WebSocket server in background thread
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# --- Main inference loop ---
fps_buffer = []

print("Streaming... connect your viewer to ws://192.168.0.131:8765")
print("Press Ctrl+C to stop")

try:
    while True:
        t0 = time.time()

        try:
            raw = picam.capture_array()
        except Exception as e:
            print("Camera error:", e)
            continue

        frame = np.ascontiguousarray(raw[:, :, 2::-1])
        h0, w0 = frame.shape[:2]

        img     = cv2.resize(frame, (input_size, input_size))
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_rgb = np.ascontiguousarray(img_rgb, dtype=np.uint8)

        mat = ncnn.Mat.from_pixels(img_rgb, ncnn.Mat.PixelType.PIXEL_RGB, input_size, input_size)
        mat.substract_mean_normalize([0, 0, 0], [1/255.0, 1/255.0, 1/255.0])

        ex = net.create_extractor()
        ex.input("in0", mat)
        ret, out = ex.extract("out0")

        if ret != 0:
            print("Inference error")
            continue

        arr  = out.numpy()
        data = arr.copy()
        del arr, out, ex

        data = data.T

        cx = data[:, 0]
        cy = data[:, 1]
        bw = data[:, 2]
        bh = data[:, 3]

        class_scores = data[:, 4:4 + num_classes]
        confs = class_scores.max(axis=1)
        cids  = class_scores.argmax(axis=1)

        mask = confs >= conf_thresh
        detections = []

        if mask.any():
            scale_x = w0 / input_size
            scale_y = h0 / input_size

            x1s = np.clip(((cx[mask] - bw[mask] / 2) * scale_x).astype(int), 0, w0 - 1)
            y1s = np.clip(((cy[mask] - bh[mask] / 2) * scale_y).astype(int), 0, h0 - 1)
            x2s = np.clip(((cx[mask] + bw[mask] / 2) * scale_x).astype(int), 0, w0 - 1)
            y2s = np.clip(((cy[mask] + bh[mask] / 2) * scale_y).astype(int), 0, h0 - 1)

            detections = list(zip(
                x1s.tolist(), y1s.tolist(),
                x2s.tolist(), y2s.tolist(),
                confs[mask].tolist(), cids[mask].tolist()
            ))

            boxes  = [[d[0], d[1], d[2], d[3]] for d in detections]
            scores = [d[4] for d in detections]
            keep   = nms(boxes, scores, nms_thresh)
            detections = [detections[i] for i in keep]

        for d in detections:
            x1, y1, x2, y2, conf, cid = d
            cid   = int(cid)
            color = bbox_colors[cid % len(bbox_colors)]
            label = f"{labels[cid]}: {int(conf * 100)}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        fps = 1.0 / (time.time() - t0)
        fps_buffer.append(fps)
        if len(fps_buffer) > 30:
            fps_buffer.pop(0)
        avg_fps = sum(fps_buffer) / len(fps_buffer)
        cv2.putText(frame, f"FPS: {avg_fps:.1f}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        with frame_lock:
            latest_frame = frame.copy()
        try:
            cv2.imshow("YOLO NCNN", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                raise KeyboardInterrupt
            elif key == ord('p'):
                fname = f"capture_{int(time.time())}.png"
                cv2.imwrite(fname, frame)
                print(f"Saved {fname}")
        except cv2.error:
            pass

except KeyboardInterrupt:
    print("Stopped")

picam.stop()
os._exit(0)
