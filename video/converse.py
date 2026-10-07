import os, json, requests
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
ES = os.environ["ES_URL"]; KEY = os.environ["ES_API_KEY"]
KB = ES.replace(".es.", ".kb.")
r = requests.post(f"{KB}/api/agent_builder/converse",
    headers={"Authorization": f"ApiKey {KEY}", "kbn-xsrf": "true", "Content-Type": "application/json"},
    json={"agent_id": "inspection-analyst", "connector_id": "mistral-medium",
          "input": "Which restaurants did the forecaster correctly flag as C?"}, timeout=180)
print(r.status_code)
json.dump(r.json(), open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "converse.json"), "w"), indent=1)
