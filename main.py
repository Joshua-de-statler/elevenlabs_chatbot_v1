# main.py
import os
import uuid
import json
from fastapi import FastAPI, Response, Form
from twilio.twiml.voice_response import VoiceResponse
from langchain_google_vertexai import ChatVertexAI
from elevenlabs.client import ElevenLabs
from supabase import create_client, Client
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from google.oauth2 import service_account

# --- AGENT PERSONA ---
SYSTEM_PROMPT = """
You are a friendly, professional, and helpful AI receptionist for a fictional automotive shop called Quantum Auto.
Your name is Rachel.
Your primary goal is to answer customer questions and help them book appointments.
You must follow these rules:
- Always be polite and cheerful.
- Keep your answers concise and to the point for a phone conversation.
- If you don't know the answer to a question, say "I'm sorry, I don't have that information, but I can connect you to a specialist. Please hold." and then end the conversation politely.
- Do not make up information you don't have.
Here is some information about Quantum Auto:
- Business Hours: 8:00 AM to 5:00 PM, Monday to Friday.
- Location: 123 Future Drive, Neo-Cape Town.
- Services: We service all makes and models of electric vehicles (EVs). We specialize in battery diagnostics and motor servicing.
- Booking: To book a service, you need the customer's full name, phone number, and vehicle model.
"""

# --- CLIENT INITIALIZATIONS AND ENHANCED DEBUGGING ---
print("---- LOADING ENVIRONMENT VARIABLES ----")
# Google Cloud
gcp_project_id = os.environ.get("GCP_PROJECT_ID")
gcp_region = os.environ.get("GCP_REGION")
google_creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
# Supabase
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

print(f"GCP_PROJECT_ID is set: {'Yes' if gcp_project_id else 'No'}")
print(f"GCP_REGION is set: {'Yes' if gcp_region else 'No'}")
print(f"GOOGLE_APPLICATION_CREDENTIALS_JSON is set: {'Yes' if google_creds_json_str else 'No'}")
print(f"SUPABASE_URL is set: {'Yes' if supabase_url else 'No'}")
print(f"SUPABASE_SERVICE_KEY is set: {'Yes' if supabase_key else 'No'}")
print("------------------------------------")

credentials = None
if google_creds_json_str:
    try:
        credentials_info = json.loads(google_creds_json_str)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
    except Exception as e:
        print(f"Error creating credentials from JSON: {e}")

llm = ChatVertexAI(
    model="gemini-2.5-flash-001",
    project=gcp_project_id,
    location=gcp_region,
    credentials=credentials,
)
elevenlabs_client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
supabase: Client = create_client(supabase_url, supabase_key)

BUCKET_NAME = "audio-files"
CONVERSATION_TABLE = "conversations"

app = FastAPI()

@app.post("/incoming-call")
def handle_incoming_call():
    response = VoiceResponse()
    response.say("Thank you for calling Quantum Auto. This is Rachel, how can I help you today?")
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    return Response(content=str(response), media_type="application/xml")

@app.post("/process-speech")
def handle_process_speech(SpeechResult: str = Form(...), CallSid: str = Form(...)):
    print(f"User said: {SpeechResult}")
    
    # --- SUPABASE READ OPERATION ---
    print(f"Attempting to read history for CallSid: {CallSid}")
    try:
        result = supabase.table(CONVERSATION_TABLE).select("history_json").eq("call_sid", CallSid).execute()
        history = []
        if result.data:
            print("Successfully retrieved previous history.")
            history_json = result.data[0]['history_json']
            history = [HumanMessage(content=msg['content']) if msg['type'] == 'human' else AIMessage(content=msg['content']) for msg in history_json]
        else:
            print("No previous history found for this call.")
    except Exception as e:
        print(f"!!! ERROR reading from Supabase: {e}")
        history = []

    ai_response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT)] + history + [HumanMessage(content=SpeechResult)])
    ai_text = ai_response.content
    print(f"Gemini responded: {ai_text}")

    new_history = history + [HumanMessage(content=SpeechResult), AIMessage(content=ai_text)]
    new_history_json = [{"type": "human", "content": msg.content} if isinstance(msg, HumanMessage) else {"type": "ai", "content": msg.content} for msg in new_history]
    
    # --- SUPABASE WRITE OPERATION ---
    print(f"Attempting to write history for CallSid: {CallSid}")
    try:
        supabase.table(CONVERSATION_TABLE).upsert({
            "call_sid": CallSid,
            "history_json": new_history_json
        }).execute()
        print("Successfully wrote history to Supabase.")
    except Exception as e:
        print(f"!!! ERROR writing to Supabase: {e}")

    audio_bytes = elevenlabs_client.generate(text=ai_text, voice="Rachel")
    
    file_name = f"{uuid.uuid4()}.mp3"
    supabase.storage.from_(BUCKET_NAME).upload(file=audio_bytes, path=file_name, file_options={"content-type": "audio/mpeg"})
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
    
    response = VoiceResponse()
    response.play(public_url)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    
    return Response(content=str(response), media_type="application/xml")