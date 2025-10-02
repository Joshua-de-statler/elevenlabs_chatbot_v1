# main.py
import os
import uuid
import json
from fastapi import FastAPI, Response, Form
from twilio.twiml.voice_response import VoiceResponse
from langchain_google_vertexai import ChatVertexAI
from elevenlabs import ElevenLabs
from supabase import create_client, Client
from langchain_core.messages import HumanMessage, AIMessage
from google.oauth2 import service_account

# --- ENHANCED DEBUGGING & CREDENTIALS LOADING ---
print("---- LOADING ENVIRONMENT VARIABLES ----")
gcp_project_id = os.environ.get("GCP_PROJECT_ID")
gcp_region = os.environ.get("GCP_REGION")
google_creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

print(f"GCP_PROJECT_ID is set: {'Yes' if gcp_project_id else 'No'}")
print(f"GCP_REGION is set: {'Yes' if gcp_region else 'No'}")
print(f"GOOGLE_APPLICATION_CREDENTIALS_JSON is set: {'Yes' if google_creds_json_str else 'No'}")

# --- EXPLICIT CREDENTIALS OBJECT CREATION ---
credentials = None
if google_creds_json_str:
    try:
        credentials_info = json.loads(google_creds_json_str)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        print("Successfully created credentials object from JSON.")
    except Exception as e:
        print(f"Error creating credentials from JSON: {e}")
else:
    print("Credentials JSON string is missing.")

print("------------------------------------")

# --- CLIENT INITIALIZATIONS ---

# Gemini LLM Client (now with explicit credentials)
llm = ChatVertexAI(
    model="gemini-2.5-flash",
    project=gcp_project_id,
    location=gcp_region,
    credentials=credentials,
)

# ElevenLabs TTS Client
elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

# Supabase Client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

BUCKET_NAME = "audio-files"
CONVERSATION_TABLE = "conversations"

# --- FASTAPI APP ---
app = FastAPI()

@app.post("/incoming-call", response_class=Response)
def handle_incoming_call():
    response = VoiceResponse()
    response.say("Hello, how can I help you today?", voice='alice')
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    return Response(content=str(response), media_type="application/xml")


@app.post("/process-speech", response_class=Response)
def handle_process_speech(SpeechResult: str = Form(...), CallSid: str = Form(...)):
    print(f"User said: {SpeechResult}")
    
    # 1. Retrieve conversation history from Supabase
    result = supabase.table(CONVERSATION_TABLE).select("history_json").eq("call_sid", CallSid).execute()
    history = []
    if result.data:
        history_json = result.data[0]['history_json']
        history = [HumanMessage(content=msg['content']) if msg['type'] == 'human' else AIMessage(content=msg['content']) for msg in history_json]

    # 2. Get text response from Gemini (with history)
    ai_response = llm.invoke(history + [HumanMessage(content=SpeechResult)])
    ai_text = ai_response.content
    print(f"Gemini responded: {ai_text}")

    # 3. Update history with the new messages
    new_history = history + [HumanMessage(content=SpeechResult), AIMessage(content=ai_text)]
    new_history_json = [{"type": "human", "content": msg.content} if isinstance(msg, HumanMessage) else {"type": "ai", "content": msg.content} for msg in new_history]
    
    # 4. Upsert the updated history to Supabase
    supabase.table(CONVERSATION_TABLE).upsert({
        "call_sid": CallSid,
        "history_json": new_history_json
    }).execute()

    # 5. Generate and upload audio -- THIS IS THE CORRECTED LINE --
    audio_bytes = elevenlabs_client.tts.generate(text=ai_text, voice="Rachel")
    
    file_name = f"{uuid.uuid4()}.mp3"
    supabase.storage.from_(BUCKET_NAME).upload(file=audio_bytes, path=file_name, file_options={"content-type": "audio/mpeg"})
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
    
    # 6. Respond with TwiML
    response = VoiceResponse()
    response.play(public_url)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    
    return Response(content=str(response), media_type="application/xml")