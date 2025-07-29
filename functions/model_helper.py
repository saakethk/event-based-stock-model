
# DEPENDENCIES
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from google import genai
from pprint import pprint
from firebase_admin import initialize_app, firestore, credentials
from google.cloud.firestore_v1.base_query import FieldFilter
import os

# LOAD ENV VARS
DEV = False
if DEV:
    cred = credentials.Certificate("model/firebase.json")
    initialize_app(cred)
else:
    initialize_app()
load_dotenv()

# LOGGER
def log(message: str):
    if True:
        pprint(message)

# GETS TIMESTAMP IN ACCESIBLE FORMAT
def get_timestamp(with_time=False, delta=4) -> str:
    now = datetime.now(timezone.utc) - timedelta(hours=delta)
    if with_time == False:
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%dT%H")

# GET DATA FROM FINNHUB
def get_data_finnhub(url: str, params: dict) -> tuple[bool, dict | str]:
    response = requests.get(f"https://finnhub.io/{url}", params=params)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# GET DATA FROM ALPACA
def get_data_alpaca(url: str, market=False) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": os.getenv("MARKET_API_KEY"),
        "APCA-API-SECRET-KEY": os.getenv("MARKET_API_SECRET")
    }
    if market:
        response = requests.get(f"https://data.alpaca.markets/{url}", headers=headers)
    else:
        response = requests.get(f"https://paper-api.alpaca.markets/{url}", headers=headers)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# POSTS DATA TO ALPACA
def post_data_alpaca(url: str, payload: dict) -> tuple[bool, dict | str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": os.getenv("MARKET_API_KEY_DEV"),
        "APCA-API-SECRET-KEY": os.getenv("MARKET_API_SECRET_DEV")
    }
    response = requests.post(f"https://paper-api.alpaca.markets/{url}", headers=headers, json=payload)
    response_object = response.json()
    if "message" in response_object:
        return False, response_object["message"]
    else:
        return True, response_object
    
# GET DATA FROM NEWS API
def get_data_news(url: str, params: dict) -> tuple[bool, dict | str]:
    response = requests.get(f"https://newsapi.org/{url}", params=params)
    response_object = response.json()
    if response_object["status"] == "error":
        return False, response_object["message"]
    else:
        return True, response.json()

# INTERFACE WITH LLM
def ask_llm(prompt: str):
    client = genai.Client(api_key=os.getenv("GOOGLE_GENAI_API_KEY"))
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

# INTERFACE WITH FIRESTORE (Modify)
def set_database(collection: str, document: str, data: dict):
    firestore_client: firestore.client = firestore.client()
    firestore_client.collection(collection).document(document).set(data)
    return True

# INTERFACE WITH FIRESTORE (Retrieve)
def get_database(collection: str, document: str):
    firestore_client: firestore.Client = firestore.client()
    ipo_ref = firestore_client.collection(collection).document(document)
    return ipo_ref.get().to_dict()

# INTERFACE WITH FIRESTORE (Retrieve group)
def get_database_collection(collection: str, field: str, value: str, key: str):
    firestore_client: firestore.client = firestore.client()
    docs = (
        firestore_client.collection(collection)
        .where(filter=FieldFilter(field, "!=", value))
        .stream()
    )
    documents = []
    for doc in docs:
        documents.append(doc.to_dict()[key])
    return documents