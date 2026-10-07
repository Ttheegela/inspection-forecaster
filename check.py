"""Connection check: Elastic + Mistral. Reads keys from .env, never prints them."""
import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from mistralai.client import Mistral

load_dotenv()

es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"])
print("Elastic:", es.info()["version"]["number"])

mistral = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
r = mistral.chat.complete(model="mistral-large-4", messages=[{"role": "user", "content": "Say OK."}])
print("Mistral:", r.choices[0].message.content)
