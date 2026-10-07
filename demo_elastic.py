"""Terminal stand-in for the Kibana Dev Tools part of the demo (snippets from devtools.txt).

Usage: python demo_elastic.py [--auto] [--step N]
"""
import json, os, sys, time, warnings
from pathlib import Path

from dotenv import load_dotenv
from elasticsearch import Elasticsearch, ElasticsearchWarning

warnings.filterwarnings("ignore", category=ElasticsearchWarning)

DIM, BOLD, CYAN, GREEN, YELLOW, MAGENTA, RESET = (f"\033[{c}m" for c in ("2", "1", "36", "32", "33", "35", "0"))
JSON_HDRS = {"accept": "application/json", "content-type": "application/json"}

ESQL_BASELINE = """FROM inspections
| WHERE zipcode == "11354" AND inspection_date < "2026-06-15" AND grade IS NOT NULL
| STATS n = COUNT(*), avg_score = AVG(score) BY grade
| SORT grade"""

ESQL_SCOREBOARD = """FROM forecasts
| EVAL agent_hit = CASE(predicted_grade == actual_grade, 1, 0),
       last_grade_hit = CASE(baseline_grade == actual_grade, 1, 0),
       last_score_hit = CASE(score_baseline_grade == actual_grade, 1, 0)
| STATS n = COUNT(*), agent = AVG(agent_hit),
        last_grade = AVG(last_grade_hit), last_score = AVG(last_score_hit)
  BY actual_grade
| SORT actual_grade"""

# Bodies kept verbatim from devtools.txt so the box shows exactly what Dev Tools would.
SEMANTIC_BODY = """{
  "size": 5,
  "_source": ["dba", "grade", "score", "inspection_date", "zipcode"],
  "query": {
    "semantic": {
      "field": "violations_text",
      "query": "mice droppings and flies near food prep, cold food held too warm"
    }
  }
}"""
LOOKUP_BODY = """{
  "size": 1,
  "_source": ["dba", "address", "zipcode", "location"],
  "query": { "term": { "camis": "50033403" } }
}"""
GEO_BODY = """{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "geo_distance": { "distance": "75m",
                            "location": { "lat": 40.760023562641, "lon": -73.828314315508 } } },
        { "range": { "created_date": { "gte": "2026-06-15||-90d", "lt": "2026-06-15" } } }
      ]
    }
  },
  "aggs": {
    "by_type": { "terms": { "field": "complaint_type" } },
    "per_week": { "date_histogram": { "field": "created_date",
                                      "calendar_interval": "week" } }
  }
}"""


def box(lines):
    w = max(len(l) for l in lines) + 2
    print(f"{DIM}┌{'─' * w}┐")
    for l in lines:
        print(f"│ {l.ljust(w - 1)}│")
    print(f"└{'─' * w}┘{RESET}")


def show_request(method, path, body=None, esql=None):
    lines = [f"{method} {path}"]
    if body is not None:
        lines += body.splitlines()
    if esql is not None:
        lines += ["{", '  "query": """'] + ["    " + l for l in esql.splitlines()] + ['  """', "}"]
    box(lines)


def table(headers, rows):
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("  " + BOLD + "  ".join(h.ljust(w) for h, w in zip(headers, widths)) + RESET)
    print("  " + "  ".join("─" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)))


def search(es, index, body):
    return es.perform_request("POST", f"/{index}/_search", body=json.loads(body), headers=JSON_HDRS).body


def esql(es, q):
    print(f"{GREEN}{es.esql.query(query=q, format='txt').body}{RESET}")


def step1(es):
    show_request("GET", "_inference/mistral-embeddings")
    ep = es.perform_request("GET", "/_inference/mistral-embeddings", headers=JSON_HDRS).body["endpoints"][0]
    s = ep["service_settings"]
    table(["inference_id", "service", "model", "task_type", "dims"],
          [[ep["inference_id"], ep["service"], s.get("model") or s.get("model_id"), ep["task_type"], s.get("dimensions", "")]])


def step2(es):
    show_request("GET", "inspections/_mapping")
    props = es.indices.get_mapping(index="inspections").body["inspections"]["mappings"]["properties"]
    rows = []
    for f in ("violations_text", "location", "grade", "score"):
        p = props[f]
        extra = f"inference_id={p['inference_id']}" if "inference_id" in p else ""
        rows.append([f, p["type"], extra])
    table(["field", "type", ""], rows)


def step3(es):
    show_request("GET", "inspections/_search", SEMANTIC_BODY)
    hits = search(es, "inspections", SEMANTIC_BODY)["hits"]["hits"]
    table(["dba", "grade", "score", "date", "zip", "relevance"],
          [[h["_source"].get("dba", "")[:38], h["_source"].get("grade") or "-", h["_source"].get("score", ""),
            str(h["_source"].get("inspection_date", ""))[:10], h["_source"].get("zipcode", ""), f"{h['_score']:.3f}"]
           for h in hits])


def step4(es):
    show_request("GET", "inspections/_search", LOOKUP_BODY)
    src = search(es, "inspections", LOOKUP_BODY)["hits"]["hits"][0]["_source"]
    loc = src["location"]
    loc = f"{loc['lat']}, {loc['lon']}" if isinstance(loc, dict) else str(loc)
    table(["dba", "address", "zip", "location"], [[src["dba"], src["address"], src["zipcode"], loc]])


def step5(es):
    show_request("GET", "complaints_311/_search", GEO_BODY)
    r = search(es, "complaints_311", GEO_BODY)
    print(f"  {BOLD}{r['hits']['total']['value']} complaints{RESET} within 75 m, 90 days before 2026-06-15\n")
    table(["complaint_type", "count"], [[b["key"], b["doc_count"]] for b in r["aggregations"]["by_type"]["buckets"]])
    print()
    table(["week_of", "count"], [[b["key_as_string"][:10], b["doc_count"]]
                                 for b in r["aggregations"]["per_week"]["buckets"] if b["doc_count"]])


def step6(es):
    show_request("POST", "_query?format=txt", esql=ESQL_BASELINE)
    esql(es, ESQL_BASELINE)


def step7(es):
    show_request("POST", "_query?format=txt", esql=ESQL_SCOREBOARD)
    esql(es, ESQL_SCOREBOARD)


STEPS = [
    ("Mistral lives inside Elastic", "The embedding model is an Elastic inference endpoint.", step1),
    ("semantic_text mapping", "violations_text is semantic_text: Elastic calls Mistral at index + query time. No vector plumbing.", step2),
    ("Semantic query", "Plain-English search over violation histories.", step3),
    ("Restaurant lookup", "Get the demo restaurant's point (camis 50033403).", step4),
    ("geo_distance + date-range 311 aggregation", "What the neighbors reported in the 90 days before the inspector showed up, within 75 meters.", step5),
    ("Neighborhood baseline in ES|QL", "Zip-code grade mix, also before the as-of date.", step6),
    ("Scoreboard in ES|QL", "Every backtest forecast was written back to an Elastic index; agent vs. baselines by actual grade.", step7),
]


def main():
    args = sys.argv[1:]
    auto = "--auto" in args
    only = int(args[args.index("--step") + 1]) if "--step" in args else None
    load_dotenv(Path(__file__).with_name(".env"))
    es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
    todo = [(i, s) for i, s in enumerate(STEPS, 1) if only in (None, i)]
    for n, (i, (title, narration, fn)) in enumerate(todo):
        print(f"\n{BOLD}{CYAN}━━ Step {i}/{len(STEPS)}  {title} {'━' * max(3, 60 - len(title))}{RESET}")
        print(f"{YELLOW}» {narration}{RESET}\n")
        fn(es)
        if n < len(todo) - 1:
            if auto:
                time.sleep(1.5)
            else:
                input(f"\n{MAGENTA}[Enter] next step{RESET}")
    print()


if __name__ == "__main__":
    main()
