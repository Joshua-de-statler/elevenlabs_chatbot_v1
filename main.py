# main.py
import os
from fastapi import FastAPI, Response, Form
from twilio.twiml.voice_response import VoiceResponse

app = FastAPI()

@app.post("/incoming-call", response_class=Response)
def handle_incoming_call():
    """Greets the caller and waits for them to speak."""
    response = VoiceResponse()
    
    response.say("Hello, how can I help you today?", voice='alice')
    
    # <Gather> listens for speech and sends the result to the /process-speech endpoint
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    
    return Response(content=str(response), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
def handle_process_speech(SpeechResult: str = Form(...)):
    """Receives the transcribed text and logs it."""
    # Log the transcribed text to our Railway console
    print(f"User said: {SpeechResult}")
    
    response = VoiceResponse()
    
    # For now, give a simple confirmation message.
    response.say("Thank you. I am processing your request.", voice='alice')
    
    return Response(content=str(response), media_type="application/xml")


@app.get("/")
def read_root():
    return {"Status": "OK"}