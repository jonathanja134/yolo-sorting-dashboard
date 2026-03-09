import asyncio
import json
import subprocess
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.signaling import BYE
from picamera2 import Picamera2
import av

class CameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.picam = Picamera2()
        self.picam.configure(self.picam.create_video_configuration(main={"size": (640, 480)}))
        self.picam.start()

    async def recv(self):
        frame = self.picam.capture_array()
        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self.time
        video_frame.time_base = self.time_base
        return video_frame

# WebSocket signaling server
import websockets

clients = set()

async def signaling_handler(ws):
    pc = RTCPeerConnection()
    pc.addTrack(CameraTrack())
    clients.add(pc)

    async for message in ws:
        data = json.loads(message)

        if data["type"] == "offer":
            await pc.setRemoteDescription(RTCSessionDescription(**data))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await ws.send(json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }))
        elif data["type"] == "ice":
            await pc.addIceCandidate(data["candidate"])
        elif data == BYE:
            await pc.close()
            break

    clients.discard(pc)

async def main():
    async with websockets.serve(signaling_handler, "0.0.0.0", 8766):
        print("WebRTC signaling server running on ws://0.0.0.0:8766")
        await asyncio.Future()  # run forever

asyncio.run(main())