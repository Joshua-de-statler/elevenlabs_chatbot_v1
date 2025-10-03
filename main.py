# main.py
import os
import json
import asyncio
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from twilio.twiml.voice_response import VoiceResponse, Connect
import websockets # Library for making outbound WebSocket connections

app = FastAPI()

ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")

@app.post("/incoming-call")
def handle_incoming_call(request: Request):
    """Handles the initial call and connects it to our WebSocket."""
    base_url = str(request.base_url).replace("http://", "ws://").replace("https://", "wss://")
    websocket_url = f"{base_url}media"

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=websocket_url)
    response.append(connect)
    response.pause(length=1)

    return Response(content=str(response), media_type="application/xml")

async def forward_twilio_to_elevenlabs(twilio_ws, elevenlabs_ws):
    """Forwards audio from Twilio to ElevenLabs."""
    try:
        while True:
            message = await twilio_ws.receive_json()
            event = message.get("event")

            if event == "media":
                payload = message["media"]["payload"]
                # Send the audio data to ElevenLabs
                await elevenlabs_ws.send(json.dumps({
                    "audio": payload,
                }))
    except WebSocketDisconnect:
        print("Twilio WebSocket disconnected during forwarding.")

async def forward_elevenlabs_to_twilio(twilio_ws, elevenlabs_ws):
    """Forwards audio from ElevenLabs back to Twilio."""
    try:
        while True:
            message_str = await elevenlabs_ws.recv()
            message = json.loads(message_str)

            if message.get("audio"):
                # The response audio is also base64 encoded
                audio_payload = message["audio"]
                # Send the agent's audio back to the caller via Twilio
                await twilio_ws.send_json({
                    "event": "media",
                    "streamSid": "your_stream_sid", # This will be dynamic in a full app
                    "media": {"payload": audio_payload}
                })
    except websockets.exceptions.ConnectionClosed:
        print("ElevenLabs WebSocket disconnected.")

@app.websocket("/media")
async def media_stream(websocket: WebSocket):
    """Manages the two-way audio stream between Twilio and ElevenLabs."""
    await websocket.accept()
    print("Twilio WebSocket connection established.")

    # URL for the ElevenLabs Agent WebSocket
    elevenlabs_websocket_url = f"wss://api.elevenlabs.io/v1/agent/{ELEVENLABS_AGENT_ID}/sockets/twilio/audio"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}

    async with websockets.connect(elevenlabs_websocket_url, extra_headers=headers) as elevenlabs_ws:
        print("ElevenLabs WebSocket connection established.")

        # Start two concurrent tasks: one for each direction of the audio stream
        task_twilio_to_elevenlabs = asyncio.create_task(forward_twilio_to_elevenlabs(websocket, elevenlabs_ws))
        task_elevenlabs_to_twilio = asyncio.create_task(forward_elevenlabs_to_twilio(websocket, elevenlabs_ws))

        # Keep the connection alive until one of the tasks finishes
        await asyncio.gather(task_twilio_to_elevenlabs, task_elevenlabs_to_twilio)

    print("Closing all connections.")