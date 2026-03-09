import gc
gc.disable()
import serial
import base64
import os
import argparse
import ncnn
import cv2
import numpy as np
import time
import asyncio
import threading
import websockets
from picamera2 import Picamera2

parser = argparse.ArgumentParser()
parser.add_argument('--model', help='Model folder', default='yolo11n')
args = parser.parse_args()

script_dir = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(script_dir, "my_model_ncnn_model", args.model)
param_file = os.path.join(model_dir, "model.ncnn.param")
bin_file   = os.path.join(model_dir, "model.ncnn.bin")

input_size  = 640
conf_thresh = 0.9
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

# -------------------
# NCNN Load
# -------------------
net = ncnn.Net()
net.opt.use_vulkan_compute = False
net.opt.num_threads        = 4
net.opt.use_fp16_packed    = True
net.opt.use_fp16_storage   = True
net.opt.use_fp16_arithmetic = True
net.opt.use_packing_layout = True

if net.load_param(param_file) != 0:
    raise RuntimeError(f"Failed to load param: {param_file}")
if net.load_model(bin_file) != 0:
    raise RuntimeError(f"Failed to load model: {bin_file}")
print("Model loaded OK")

# -------------------
# Camera
# -------------------
picam = Picamera2()
picam.configure(picam.create_video_configuration(
    main={"size": (input_size, input_size), "format": "YUV420"}
))
picam.start()
print("Camera OK")

# -------------------
# Shared buffers
# -------------------
# Latest annotated frame (for display)
latest_frame = None
frame_lock = threading.Lock()

# Pre-encoded JPEG bytes (for websocket) - encoded in parallel thread
encoded_buf = None
encoded_lock = threading.Lock()
encode_event = threading.Event()  # signals encoder thread that new frame is ready

# -------------------
# NMS
# -------------------
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

# -------------------
# Encoder thread
# Runs independently, encodes latest_frame to JPEG
# whenever the main loop signals a new frame is ready
# -------------------
encoder_running = True

def encoder_thread_fn():
    global encoded_buf
    while encoder_running:
        # Wait for main loop to signal a new frame
        encode_event.wait(timeout=0.1)
        encode_event.clear()

        with frame_lock:
            frame = latest_frame
        if frame is None:
            continue

        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        with encoded_lock:
            encoded_buf = buf.tobytes()

encoder_thread = threading.Thread(target=encoder_thread_fn, daemon=True)
encoder_thread.start()

# -------------------
# WebSocket server
# Sends pre-encoded JPEG from encoder thread
# -------------------
yolo_clients = set()

async def yolo_handler(websocket):
    yolo_clients.add(websocket)
    print(f"YOLO client connected: {websocket.remote_address}")
    try:
        while True:
            with encoded_lock:
                buf = encoded_buf
            if buf is not None:
                await websocket.send(buf)
            await asyncio.sleep(0.033)  # ~30fps cap
    except websockets.exceptions.ConnectionClosed:
        print("YOLO client disconnected")
    finally:
        yolo_clients.discard(websocket)

async def run_server():
    print("YOLO WebSocket running on ws://0.0.0.0:8765")
    async with websockets.serve(yolo_handler, "0.0.0.0", 8765):
        await asyncio.Future()

def start_server():
    asyncio.run(run_server())

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# -------------------
# Main inference loop
# -------------------
fps_buffer = []

print("Streaming... connect your viewer to ws://192.168.0.13:8765")
print("Press Ctrl+C to stop")

try:
    while True:
        t0 = time.time()

        # Capture frame
        try:
            raw = picam.capture_array()
        except Exception as e:
            print("Camera error:", e)
            continue

        # Convert YUV420 -> BGR
        frame = np.ascontiguousarray(cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420))
        h0, w0 = frame.shape[:2]

        # Build ncnn input
        mat = ncnn.Mat.from_pixels(
            frame,
            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            input_size,
            input_size
        )
        mat.substract_mean_normalize([0, 0, 0], [1/255.0, 1/255.0, 1/255.0])

        # Inference
        ex = net.create_extractor()
        ex.input("in0", mat)
        ret, out = ex.extract("out0")

        if ret != 0:
            print("Inference error")
            continue

        arr  = out.numpy()
        data = arr.copy()
        del arr, out, ex

        # Decode output - shape is [num_classes+4, 8400] transposed
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

        # Draw boxes
        for d in detections:
            x1, y1, x2, y2, conf, cid = d
            cid   = int(cid)
            color = bbox_colors[cid % len(bbox_colors)]
            label = f"{labels[cid]}: {int(conf * 100)}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # FPS overlay
        fps = 1.0 / (time.time() - t0)
        fps_buffer.append(fps)
        if len(fps_buffer) > 30:
            fps_buffer.pop(0)
        avg_fps = sum(fps_buffer) / len(fps_buffer)
        cv2.putText(frame, f"FPS: {avg_fps:.1f}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # Update shared frame and signal encoder thread
        with frame_lock:
            latest_frame = frame.copy()
        encode_event.set()  # wake encoder thread immediately

        # Local display (comment out if only using websocket)
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

encoder_running = False
picam.stop()
os._exit(0)
