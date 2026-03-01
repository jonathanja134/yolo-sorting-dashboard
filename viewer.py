import asyncio
import websockets
import cv2
import numpy as np

PI_ADDRESS = "ws://192.168.0.131:8765"

async def view_stream():
    print(f"Connecting to {PI_ADDRESS} ...")
    async with websockets.connect(PI_ADDRESS) as ws:
        print("Connected! Press ESC to quit.")
        while True:
            data = await ws.recv()
            buf = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if frame is not None:
                cv2.imshow("YOLO Stream from Pi", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    cv2.destroyAllWindows()

asyncio.run(view_stream())