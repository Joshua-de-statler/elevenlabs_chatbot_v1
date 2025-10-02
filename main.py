# main.py
import os
from fastapi import FastAPI, Response, Form
from twilio.twiml.voice_response import VoiceResponse
from langchain_google_vertexai import ChatVertexAI

# Explicitly initialize the Gemini LLM with project and location
llm = ChatVertexAI(
    model="gemini-2.5-flash-001",
    project=os.environ.get("GCP_PROJECT_ID"),
    location=os.environ.get("GCP_REGION"),
)

app = FastAPI()

@app.post("/incoming-call", response_class=Response)
def handle_incoming_call():
    """Greets the caller and waits for them to speak."""
    response = VoiceResponse()
    response.say("Hello, how can I help you today?", voice='alice')
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    return Response(content=str(response), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
def handle_process_speech(SpeechResult: str = Form(...)):
    """Processes user's speech, gets a response from Gemini, and logs it."""
    print(f"User said: {SpeechResult}")
    
    # Get a response from the LLM
    ai_response = llm.invoke(SpeechResult)
    ai_text = ai_response.content
    
    # Log the AI's response
    print(f"Gemini responded: {ai_text}")
    
    response = VoiceResponse()
    # We will still use a static message for now. The next step is to speak the AI's response.
    response.say("Thank you. I am processing your request.", voice='alice')
    
    return Response(content=str(response), media_type="application/xml")


@app.get("/")
def read_root():
    return {"Status": "OK"}