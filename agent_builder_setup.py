"""Create a Kibana Agent Builder agent ("Inspection Analyst") that thinks with Mistral Large 4
and answers questions over the inspections / 311 / forecasts indices. Idempotent: re-run safe."""
import os

import requests
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv(".env")
KB = os.environ["ES_URL"].replace(".es.", ".kb.")
H = {"Authorization": f"ApiKey {os.environ['ES_API_KEY']}", "kbn-xsrf": "true"}
es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"])

# 1. Mistral Large 4 as an Elastic chat_completion endpoint (the agent's brain)
try:
    es.inference.put(inference_id="mistral-chat", task_type="chat_completion", inference_config={
        "service": "mistral",
        "service_settings": {"api_key": os.environ["MISTRAL_API_KEY"], "model": "mistral-large-4"},
    })
    print("created inference endpoint mistral-chat")
except Exception as e:
    print("mistral-chat:", str(e)[:100])

# 2. ES|QL + search tools
TOOLS = [
    ("nyc.forecast_scoreboard", "esql",
     "Backtest scoreboard: accuracy of the Mistral forecaster vs the two naive baselines, by actual grade.",
     {"query": "FROM forecasts | EVAL agent_hit = CASE(predicted_grade == actual_grade, 1, 0), "
               "last_grade_hit = CASE(baseline_grade == actual_grade, 1, 0), "
               "last_score_hit = CASE(score_baseline_grade == actual_grade, 1, 0) "
               "| STATS n = COUNT(*), agent = AVG(agent_hit), last_grade = AVG(last_grade_hit), "
               "last_score = AVG(last_score_hit) BY actual_grade | SORT actual_grade", "params": {}}),
    ("nyc.forecasts", "esql",
     "Every backtested forecast: restaurant, date, actual vs predicted grade/score, baselines, confidence, reasoning.",
     {"query": "FROM forecasts | KEEP camis, dba, as_of, actual_grade, actual_score, predicted_grade, "
               "predicted_score, baseline_grade, score_baseline_grade, confidence, reasoning "
               "| SORT actual_grade, dba | LIMIT 100", "params": {}}),
    ("nyc.restaurant_history", "esql",
     "Inspection history of one restaurant by CAMIS id: dates, type, score, grade, violations.",
     {"query": "FROM inspections | WHERE camis == ?camis | SORT inspection_date "
               "| KEEP dba, address, zipcode, inspection_date, inspection_type, score, grade, violations | LIMIT 20",
      "params": {"camis": {"type": "string", "description": "Restaurant CAMIS id, e.g. 50033403"}}}),
    ("nyc.zipcode_risk", "esql",
     "Grade mix and average inspection score for a NYC zipcode (higher score = worse).",
     {"query": "FROM inspections | WHERE zipcode == ?zip AND grade IN (\"A\", \"B\", \"C\") "
               "| STATS inspections = COUNT(*), avg_score = AVG(score) BY grade | SORT grade",
      "params": {"zip": {"type": "string", "description": "5-digit zipcode, e.g. 11354"}}}),
    ("nyc.complaints_by_borough", "esql",
     "311 rodent / food poisoning / food establishment complaint counts by borough and type since a date.",
     {"query": "FROM complaints_311 | WHERE created_date >= TO_DATETIME(?since) "
               "| STATS complaints = COUNT(*) BY borough, complaint_type | SORT complaints DESC | LIMIT 30",
      "params": {"since": {"type": "string", "description": "ISO date, e.g. 2026-01-01"}}}),
    ("nyc.search_violations", "index_search",
     "Semantic search (Mistral embeddings) over restaurant inspection violation text. Use for questions "
     "about kinds of violations, e.g. 'pests near food', 'unsafe cold holding'.",
     {"pattern": "inspections"}),
]

for tid, ttype, desc, cfg in TOOLS:
    requests.delete(f"{KB}/api/agent_builder/tools/{tid}", headers=H)
    r = requests.post(f"{KB}/api/agent_builder/tools", headers=H,
                      json={"id": tid, "type": ttype, "description": desc, "configuration": cfg, "tags": ["nyc"]})
    print(tid, r.status_code, "" if r.ok else r.text[:300])

# Agent Builder can't parse Large 4's thinking chunks, so the agent's chat model is Mistral Medium
try:
    es.inference.put(inference_id="mistral-medium-chat", task_type="chat_completion", inference_config={
        "service": "mistral",
        "service_settings": {"api_key": os.environ["MISTRAL_API_KEY"], "model": "mistral-medium-latest"},
    })
except Exception as e:
    print("mistral-medium-chat:", str(e)[:100])
r = requests.post(f"{KB}/api/kibana/settings", headers=H,
                  json={"changes": {"genAiSettings:defaultAIConnector": "mistral-medium-chat"}})
print("default AI connector -> mistral-medium-chat", r.status_code, "" if r.ok else r.text[:200])

# 3. The agent
AGENT_ID = "inspection-analyst"
requests.delete(f"{KB}/api/agent_builder/agents/{AGENT_ID}", headers=H)
r = requests.post(f"{KB}/api/agent_builder/agents", headers=H, json={
    "id": AGENT_ID,
    "name": "NYC Inspection Analyst",
    "description": "Explains the Inspection Forecaster backtest and answers questions over NYC restaurant "
                   "inspections and 311 complaints. Powered by Mistral Large 4.",
    "configuration": {
        "instructions": (
            "You analyze NYC DOHMH restaurant inspections (index `inspections`, score: higher = worse; "
            "A = 0-13, B = 14-27, C = 28+), 311 complaints (`complaints_311`: Rodent, Food Poisoning, Food "
            "Establishment, with locations) and the Inspection Forecaster backtest (`forecasts`). The forecaster "
            "is a Mistral Large 4 agent that predicts a restaurant's grade using only evidence dated before the "
            "inspection; it was compared with two naive baselines ('same grade as last time', 'last score -> band'). "
            "Never announce what you will do; call the nyc.* tool immediately, then answer from its result. Cite numbers, restaurant names and dates. Be concise; use tables. "
            "When comparing the forecaster with baselines, read the numbers carefully and only claim it is "
            "better where its number is strictly higher. Headline: it catches 9 of 10 C restaurants (best of all), "
            "but over-flags A restaurants, so overall accuracy is 43% vs 47% for the best baseline."),
        "tools": [{"tool_ids": [t[0] for t in TOOLS]}],
    },
})
print("agent", r.status_code, "" if r.ok else r.text[:400])
