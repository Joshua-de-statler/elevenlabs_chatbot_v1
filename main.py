# main.py
import os
import uuid
from fastapi import FastAPI, Response, Form
from twilio.twiml.voice_response import VoiceResponse
from langchain_google_vertexai import ChatVertexAI
# CORRECTED IMPORT STATEMENT
from elevenlabs import ElevenLabs 
from supabase import create_client, Client

# --- CLIENT INITIALIZATIONS ---

# Gemini LLM Client
llm = ChatVertexAI(
    model="gemini-2.5-flash-001",
    project=os.environ.get("GCP_PROJECT_ID"),
    location=os.environ.get("GCP_REGION"),
)

# CORRECTED ELEVENLABS CLIENT INITIALIZATION
elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

# Supabase Storage Client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

BUCKET_NAME = "audio-files" # The public bucket you created

# --- FASTAPI APP ---

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
    """Processes speech, generates AI audio, and plays it back."""
    print(f"User said: {SpeechResult}")

    # 1. Get text response from Gemini
    ai_response = llm.invoke(SpeechResult)
    ai_text = ai_response.content
    print(f"Gemini responded: {ai_text}")

    # 2. Generate audio from ElevenLabs
    audio_bytes = elevenlabs_client.generate(text=ai_text, voice="Rachel")

    # 3. Upload audio to Supabase Storage
    file_name = f"{uuid.uuid4()}.mp3"
    supabase.storage.from_(BUCKET_NAME).upload(file=audio_bytes, path=file_name, file_options={"content-type": "audio/mpeg"})

    # 4. Get the public URL for the audio file
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
    print(f"Audio URL: {public_url}")

    # 5. Respond with TwiML to play the audio and continue the conversation
    response = VoiceResponse()
    response.play(public_url)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')

    return Response(content=str(response), media_type="application/xml")

@app.get("/")
def read_root():
    return {"Status": "OK"}