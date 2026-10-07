"""Load inspections + 311 complaints into Elasticsearch.

- Mistral embedding endpoint registered inside Elastic (semantic_text on violation text)
- inspections: one doc per (restaurant, inspection date), violation lines rolled up
- complaints_311: geo_point + date for "what did neighbors report before the inspection"
"""
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers

load_dotenv()
STEPS = sys.argv[1:] or ['mistral', 'inspections', '311']  # e.g. python ingest.py 311
es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=300)

# 1. Mistral embeddings as an Elastic inference endpoint
if 'mistral' in STEPS:
    try:
        es.inference.put(inference_id="mistral-embeddings", task_type="text_embedding", inference_config={
            "service": "mistral",
            "service_settings": {"api_key": os.environ["MISTRAL_API_KEY"], "model": "mistral-embed"},
        })
        print("created inference endpoint mistral-embeddings")
    except Exception as e:
        print("inference endpoint:", str(e)[:120])


def recreate(index, props):
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
    es.indices.create(index=index, mappings={"properties": props})


# 2. Inspections: roll violation lines up to one doc per inspection
if 'inspections' in STEPS:
    rows = json.load(open("data/inspections.json"))
    insp = defaultdict(lambda: {"violations": [], "codes": []})
    for r in rows:
        d = insp[(r["camis"], r["inspection_date"][:10])]
        d.update({
            "camis": r["camis"], "dba": r.get("dba"), "cuisine": r.get("cuisine_description"),
            "boro": r.get("boro"), "zipcode": r.get("zipcode"),
            "address": f"{r.get('building', '')} {r.get('street', '')}".strip(),
            "inspection_date": r["inspection_date"][:10], "inspection_type": r.get("inspection_type"),
            "location": {"lat": float(r["latitude"]), "lon": float(r["longitude"])},
        })
        if r.get("score"):
            d["score"] = int(r["score"])
        if r.get("grade"):
            d["grade"] = r["grade"]
        if r.get("violation_description"):
            d["violations"].append(r["violation_description"])
            d["codes"].append(r.get("violation_code"))

    docs = [d | {"violations_text": " | ".join(d["violations"]) or "No violations recorded"}
            for d in insp.values() if d["location"]["lat"] != 0]

    recreate("inspections", {
        "camis": {"type": "keyword"}, "dba": {"type": "keyword"}, "cuisine": {"type": "keyword"},
        "boro": {"type": "keyword"}, "zipcode": {"type": "keyword"}, "address": {"type": "keyword"},
        "inspection_date": {"type": "date"}, "inspection_type": {"type": "keyword"},
        "score": {"type": "integer"}, "grade": {"type": "keyword"},
        "violations": {"type": "text"}, "codes": {"type": "keyword"},
        "violations_text": {"type": "semantic_text", "inference_id": "mistral-embeddings"},
        "location": {"type": "geo_point"},
    })
    ok, err = helpers.bulk(es, ({"_index": "inspections", "_source": d} for d in docs),
                           chunk_size=200, raise_on_error=False)
    print(f"inspections: {ok} indexed, {len(err)} errors")

# 3. 311 complaints
if '311' in STEPS:
    rows = json.load(open("data/complaints_311.json"))
    recreate("complaints_311", {
        "created_date": {"type": "date"}, "complaint_type": {"type": "keyword"},
        "descriptor": {"type": "keyword"}, "address": {"type": "keyword"},
        "borough": {"type": "keyword"}, "location": {"type": "geo_point"},
    })
    ok, err = helpers.bulk(es, ({"_index": "complaints_311", "_id": r["unique_key"], "_source": {
        "created_date": r["created_date"], "complaint_type": r["complaint_type"],
        "descriptor": r.get("descriptor"), "address": r.get("incident_address"), "borough": r.get("borough"),
        "location": {"lat": float(r["latitude"]), "lon": float(r["longitude"])},
    }} for r in rows), raise_on_error=False)
    print(f"complaints_311: {ok} indexed, {len(err)} errors")
