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

# --- NEW AGENT PERSONA ---
SYSTEM_PROMPT = """
# Personality

You are a helpful assistant named AssistBot. You are friendly, patient, and efficient.

# Environment

You are interacting with users via voice. The user is seeking assistance with various tasks.

# Tone

Your responses are clear, concise, and polite. You use a conversational style with natural speech patterns.

# Goal

Your primary goal is to assist users with their requests efficiently and accurately.

1.  Understand the user's request.
2.  Provide helpful information or complete the task.
3.  Ensure the user is satisfied with the response.

# Guardrails

Remain within the scope of general knowledge and common tasks. Avoid providing harmful or unethical advice. If you don't know the answer, admit it and suggest alternative resources.
"""

# --- CLIENT INITIALIZATIONS AND DEBUGGING ---
# This section remains the same for robust authentication.
print("---- LOADING ENVIRONMENT VARIABLES ----")
gcp_project_id = os.environ.get("GCP_PROJECT_ID")
gcp_region = os.environ.get("GCP_REGION")
google_creds_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

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
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

BUCKET_NAME = "audio-files"
CONVERSATION_TABLE = "conversations"

app = FastAPI()

@app.post("/incoming-call")
def handle_incoming_call():
    """Greets the caller with the new AssistBot persona."""
    response = VoiceResponse()
    response.say("Hello, you've reached AssistBot. How can I help you today?")
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    return Response(content=str(response), media_type="application/xml")

@app.post("/process-speech")
def handle_process_speech(SpeechResult: str = Form(...), CallSid: str = Form(...)):
    """Handles the conversation without customer-specific data."""
    print(f"User said: {SpeechResult}")
    
    # Retrieve conversation history
    result = supabase.table(CONVERSATION_TABLE).select("history_json").eq("call_sid", CallSid).execute()
    history = []
    if result.data:
        history_json = result.data[0]['history_json']
        history = [HumanMessage(content=msg['content']) if msg['type'] == 'human' else AIMessage(content=msg['content']) for msg in history_json]

    # Invoke the LLM with the new system prompt and conversation history
    ai_response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT)] + history + [HumanMessage(content=SpeechResult)])
    ai_text = ai_response.content
    print(f"Gemini responded: {ai_text}")

    # Update and save the conversation history
    new_history = history + [HumanMessage(content=SpeechResult), AIMessage(content=ai_text)]
    new_history_json = [{"type": "human", "content": msg.content} if isinstance(msg, HumanMessage) else {"type": "ai", "content": msg.content} for msg in new_history]
    
    supabase.table(CONVERSATION_TABLE).upsert({
        "call_sid": CallSid,
        "history_json": new_history_json
    }).execute()

    # Generate audio and respond to the user
    audio_bytes = elevenlabs_client.generate(text=ai_text, voice="Rachel")
    
    file_name = f"{uuid.uuid4()}.mp3"
    supabase.storage.from_(BUCKET_NAME).upload(file=audio_bytes, path=file_name, file_options={"content-type": "audio/mpeg"})
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
    
    response = VoiceResponse()
    response.play(public_url)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    
    return Response(content=str(response), media_type="application/xml")