# main.py
import os
from fastapi import FastAPI, Response
from twilio.twiml.voice_response import VoiceResponse

app = FastAPI()

@app.post("/incoming-call", response_class=Response)
def handle_incoming_call():
    """Handles incoming calls from Twilio."""
    # Create a new TwiML response
    response = VoiceResponse()
    
    # Use the <Say> verb to read a message
    response.say("Hello, and welcome. The connection to our server is successful.", voice='alice')
    
    # Return the TwiML as an XML string
    return Response(content=str(response), media_type="application/xml")

@app.get("/")
def read_root():
    return {"Status": "OK"}