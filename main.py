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

# --- BASE AGENT PERSONA ---
# This is the template for our agent. We will fill in the details later.
BASE_SYSTEM_PROMPT = """
You are an efficient AI assistant for Zappiess AI, a provider of AI solutions tailored to the unique needs of South Africa's custom home builders. You provide callers with account information directly and without unnecessary conversation.

Your responses are brief, clear, and professional. Do not engage in small talk. Be direct and to the point.

Your primary goal is to provide callers with accurate account information efficiently.
1. Greet the caller using their name.
2. Provide the caller with their account balance.
3. Answer any questions the caller has about their account.
4. If a request is outside your capabilities, state it directly and offer a transfer to a human agent for further assistance.

Do not provide information about Zappiess AI's services or products.

Caller's Name: {caller_name}
Account Balance: R{account_balance}
"""

# --- CLIENT INITIALIZATIONS ---
# This section remains the same for robust authentication.
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
CUSTOMER_TABLE = "customers" # New table for customer data

app = FastAPI()

@app.post("/incoming-call")
def handle_incoming_call(Caller: str = Form(...)):
    """Greets the caller and prepares the AI persona based on their phone number."""
    
    # --- CUSTOMER LOOKUP ---
    print(f"Incoming call from: {Caller}")
    customer_name = "Valued Customer" # Default name
    greeting = "Hello, and welcome to Zappiess AI." # Default greeting

    try:
        result = supabase.table(CUSTOMER_TABLE).select("name").eq("phone_number", Caller).single().execute()
        if result.data:
            customer_name = result.data.get("name", customer_name)
            print(f"Found customer: {customer_name}")
            greeting = f"Hello, {customer_name}." # Personalized greeting
    except Exception as e:
        print(f"Could not find customer with phone number {Caller}. Error: {e}")

    response = VoiceResponse()
    response.say(greeting)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    return Response(content=str(response), media_type="application/xml")

@app.post("/process-speech")
def handle_process_speech(SpeechResult: str = Form(...), CallSid: str = Form(...), Caller: str = Form(...)):
    print(f"User said: {SpeechResult}")

    # --- DYNAMIC PROMPT INJECTION ---
    customer_name = "Valued Customer"
    account_balance = "not available"
    try:
        result = supabase.table(CUSTOMER_TABLE).select("name, balance").eq("phone_number", Caller).single().execute()
        if result.data:
            customer_name = result.data.get("name", customer_name)
            account_balance = str(result.data.get("balance", account_balance))
    except Exception as e:
        print(f"Error retrieving customer details during conversation: {e}")

    # Format the system prompt with the customer's data
    system_prompt = BASE_SYSTEM_PROMPT.format(caller_name=customer_name, account_balance=account_balance)
    
    # --- CONVERSATION HISTORY & LLM CALL ---
    result = supabase.table(CONVERSATION_TABLE).select("history_json").eq("call_sid", CallSid).execute()
    history = []
    if result.data:
        history_json = result.data[0]['history_json']
        history = [HumanMessage(content=msg['content']) if msg['type'] == 'human' else AIMessage(content=msg['content']) for msg in history_json]

    ai_response = llm.invoke([SystemMessage(content=system_prompt)] + history + [HumanMessage(content=SpeechResult)])
    ai_text = ai_response.content
    print(f"Gemini responded: {ai_text}")

    # --- DATABASE & AUDIO ---
    new_history = history + [HumanMessage(content=SpeechResult), AIMessage(content=ai_text)]
    new_history_json = [{"type": "human", "content": msg.content} if isinstance(msg, HumanMessage) else {"type": "ai", "content": msg.content} for msg in new_history]
    
    supabase.table(CONVERSATION_TABLE).upsert({"call_sid": CallSid, "history_json": new_history_json}).execute()

    audio_bytes = elevenlabs_client.generate(text=ai_text, voice="Rachel")
    
    file_name = f"{uuid.uuid4()}.mp3"
    supabase.storage.from_(BUCKET_NAME).upload(file=audio_bytes, path=file_name, file_options={"content-type": "audio/mpeg"})
    public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_name)
    
    response = VoiceResponse()
    response.play(public_url)
    response.gather(input='speech', action='/process-speech', speech_timeout='auto')
    
    return Response(content=str(response), media_type="application/xml")