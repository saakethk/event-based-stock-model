
# DEPENDENCIES
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from google import genai
from pprint import pprint
from firebase_admin import initialize_app, firestore, credentials
from google.cloud.firestore_v1.base_query import FieldFilter
import json
import google.auth
from google.auth.transport.requests import AuthorizedSession
import os
from google.cloud import tasks_v2
from requests_oauthlib import OAuth1Session

# LOAD ENV VARS
DEV = True
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
        "APCA-API-KEY-ID": os.getenv("MARKET_API_KEY_DEV"),
        "APCA-API-SECRET-KEY": os.getenv("MARKET_API_SECRET_DEV")
    }
    if market:
        response = requests.get(f"https://data.alpaca.markets/{url}", headers=headers)
    else:
        response = requests.get(f"https://paper-api.alpaca.markets/{url}", headers=headers)
    print(response.json())
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
    firestore_client.collection(collection).document(document).set(data, merge=True)
    return True

# INTERFACE WITH FIRESTORE (Retrieve)
def get_database(collection: str, document: str):
    firestore_client: firestore.Client = firestore.client()
    ref = firestore_client.collection(collection).document(document)
    return ref.get().to_dict()

# INTERFACE WITH FIRESTORE (Retrieve group)
def get_database_collection(collection: str, field: str, value: str, operator: str, key: str):
    firestore_client: firestore.client = firestore.client()
    docs = (
        firestore_client.collection(collection)
        .where(filter=FieldFilter(field, operator, value))
        .stream()
    )
    ids = []
    documents = []
    for doc in docs:
        ids.append(doc.id)
        documents.append(doc.to_dict()[key])
    return ids, documents

# GETS FIREBASE FUNCTION URL
def get_function_url(name: str, location: str = "us-central1") -> str:
    credentials, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    authed_session = AuthorizedSession(credentials)
    url = ("https://cloudfunctions.googleapis.com/v2beta/" +
           f"projects/{project_id}/locations/{location}/functions/{name}")
    response = authed_session.get(url)
    data = response.json()
    function_url = data["serviceConfig"]["uri"]
    return function_url

# QUEUES TASK IN FIREBASE FUNCTIONS
def queue_task(function_id: str, data: dict, execute_time: datetime):
    client = tasks_v2.CloudTasksClient()
    project = "nous-486de"
    queue = function_id
    location = "us-central1"
    service_account_email = "firebase-adminsdk-fbsvc@nous-486de.iam.gserviceaccount.com"
    parent = client.queue_path(project, location, queue)
    task = tasks_v2.Task(http_request={
            "http_method": tasks_v2.HttpMethod.POST,
            "url": get_function_url(function_id),
            "headers": {
                "Content-type": "application/json"
            },
            "body": json.dumps(data).encode(),
            "oidc_token": {
                "service_account_email": service_account_email
            }
        },
        schedule_time=execute_time
    )
    response = client.create_task(parent=parent, task=task)
    return response.name

# POSTS TWEET VIA TWITTER API V2
def create_tweet(payload: dict):

    # Make the request
    oauth = OAuth1Session(
        os.getenv("TWITTER_API_KEY"),
        client_secret=os.getenv("TWITTER_API_SECRET"),
        resource_owner_key=os.getenv("TWITTER_ACCESS_TOKEN"),
        resource_owner_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
    )

    # Making the request
    response = oauth.post(
        "https://api.twitter.com/2/tweets",
        json=payload,
    )
    if response.status_code != 201:
        log(f"TWEET POST FAILED: {response.status_code} {response.text}")
        return False, response.text

    # Returns tweet id
    return True, response.json()["data"]["id"]