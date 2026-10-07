"""Inspection Forecaster: Mistral agent predicts a NYC restaurant's next inspection grade
using only Elasticsearch evidence dated strictly before `as_of` (leakage guard lives in the tools)."""
import json
import os
import sys
from functools import cache
from typing import Literal

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from mistralai.client import Mistral
from pydantic import BaseModel

MODEL = "mistral-large-4"
MAX_ROUNDS = 6
SYSTEM = """You are a NYC DOHMH restaurant inspection risk analyst. Forecast the score and grade of the
restaurant's NEXT inspection on {as_of}. You only see evidence dated before {as_of}; the tools enforce this.
Scoring: points per violation, higher = worse. A = 0-13, B = 14-27, C = 28+.
Use the tools: start with the restaurant's own history (strongest signal: recent scores, repeat violations,
trend), then nearby 311 complaints (rodents, food poisoning), the zipcode baseline, and optionally similar
violation patterns. Be concise. Cite concrete evidence (dates, scores, counts) in your reasoning.
Calibration (learned from backtesting v1, which over-predicted B by regressing to the mean):
- The most recent inspection score (graded or not) is the strongest predictor. Re-inspections usually land
  in the same band: a restaurant that scored 28+ last time most often scores 28+ again.
- Anchor on the last score, then adjust by at most ~8 points using trend, repeat violations, 311 complaints,
  and the zipcode baseline. Do not assume improvement without evidence of it.
- With no prior history, start from the zipcode baseline average."""


class Forecast(BaseModel):
    predicted_grade: Literal["A", "B", "C"]
    predicted_score: int
    likely_violations: list[str]
    confidence: float
    reasoning: str


@cache
def clients():
    load_dotenv()
    return (Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=60),
            Mistral(api_key=os.environ["MISTRAL_API_KEY"], timeout_ms=180000))


def grade_of(score):
    return None if score is None else "A" if score <= 13 else "B" if score <= 27 else "C"


def make_tools(camis, as_of):
    """Tool implementations closed over (camis, as_of): the model can never pick dates or another restaurant."""
    es = clients()[0]
    before = {"range": {"inspection_date": {"lt": as_of}}}
    # Static metadata (name/location/zip) is not outcome data, so any doc of this restaurant is fine.
    hit = es.search(index="inspections", size=1, query={"term": {"camis": camis}},
                    source=["dba", "cuisine", "address", "zipcode", "boro", "location"])["hits"]["hits"]
    meta = hit[0]["_source"] if hit else {}

    def get_inspection_history():
        hits = es.search(index="inspections", size=8, sort=[{"inspection_date": "desc"}],
                         query={"bool": {"filter": [{"term": {"camis": camis}}, before]}},
                         source=["inspection_date", "inspection_type", "score", "grade", "violations"])["hits"]["hits"]
        rows = [{"date": s["inspection_date"], "type": s.get("inspection_type"), "score": s.get("score"),
                 "grade": s.get("grade"), "violations": [v[:90] for v in s.get("violations", [])][:6]}
                for s in (h["_source"] for h in hits)]
        data = {k: meta.get(k) for k in ("dba", "cuisine", "address", "zipcode", "boro")} | {"prior_inspections": rows}
        scores = [r["score"] for r in rows if r["score"] is not None]
        return data, f"{meta.get('dba')} ({meta.get('cuisine')}): {len(rows)} prior inspections, recent scores {scores[:5]}"

    def nearby_complaints(radius_m=75, days=90):
        radius_m, days = min(int(radius_m), 500), min(int(days), 365)
        if "location" not in meta:
            return {"error": "no location"}, "no location"
        r = es.search(index="complaints_311", size=5, sort=[{"created_date": "desc"}],
                      query={"bool": {"filter": [
                          {"geo_distance": {"distance": f"{radius_m}m", "location": meta["location"]}},
                          {"range": {"created_date": {"gte": f"{as_of}||-{days}d", "lt": as_of}}}]}},
                      aggs={"by_type": {"terms": {"field": "complaint_type"}}},
                      source=["created_date", "complaint_type", "descriptor", "address"])
        counts = {b["key"]: b["doc_count"] for b in r["aggregations"]["by_type"]["buckets"]}
        examples = [{"date": s["created_date"][:10], "type": s["complaint_type"], "descriptor": s.get("descriptor"),
                     "address": s.get("address")} for s in (h["_source"] for h in r["hits"]["hits"])]
        return ({"radius_m": radius_m, "days": days, "counts": counts, "recent_examples": examples},
                f"{sum(counts.values())} complaints within {radius_m}m / {days}d: {counts or 'none'}")

    def neighborhood_baseline(days=365):
        days = min(int(days), 730)
        r = es.search(index="inspections", size=0, query={"bool": {
            "filter": [{"term": {"zipcode": meta.get("zipcode")}},
                       {"range": {"inspection_date": {"gte": f"{as_of}||-{days}d", "lt": as_of}}}],
            "must_not": [{"term": {"camis": camis}}]}},
            aggs={"avg_score": {"avg": {"field": "score"}},
                  "restaurants": {"cardinality": {"field": "camis"}},
                  "bands": {"range": {"field": "score", "ranges": [
                      {"key": "A", "to": 14}, {"key": "B", "from": 14, "to": 28}, {"key": "C", "from": 28}]}},
                  "top_codes": {"terms": {"field": "codes", "size": 5}}})
        a = r["aggregations"]
        avg = round(a["avg_score"]["value"] or 0, 1)
        bands = {b["key"]: b["doc_count"] for b in a["bands"]["buckets"]}
        data = {"zipcode": meta.get("zipcode"), "inspections": r["hits"]["total"]["value"],
                "restaurants": a["restaurants"]["value"], "avg_score": avg, "score_band_counts": bands,
                "top_violation_codes": [b["key"] for b in a["top_codes"]["buckets"]]}
        return data, f"zip {meta.get('zipcode')}: avg score {avg}, bands {bands}"

    def similar_violation_restaurants(query):
        hits = es.search(index="inspections", size=5, query={"bool": {
            "must": [{"semantic": {"field": "violations_text", "query": str(query)[:500]}}],
            "filter": [before], "must_not": [{"term": {"camis": camis}}]}},
            source=["camis", "dba", "inspection_date", "score"])["hits"]["hits"]
        out = []
        for s in (h["_source"] for h in hits):  # their NEXT inspection, still strictly before as_of
            nxt = es.search(index="inspections", size=1, sort=[{"inspection_date": "asc"}],
                            query={"bool": {"filter": [{"term": {"camis": s["camis"]}},
                                   {"range": {"inspection_date": {"gt": s["inspection_date"], "lt": as_of}}}]}},
                            source=["inspection_date", "score"])["hits"]["hits"]
            n = nxt[0]["_source"] if nxt else {}
            out.append({"dba": s.get("dba"), "date": s["inspection_date"], "score": s.get("score"),
                        "next_score": n.get("score"), "next_grade_band": grade_of(n.get("score"))})
        return {"matches": out}, f"{len(out)} similar: next scores {[o['next_score'] for o in out]}"

    return {f.__name__: f for f in (get_inspection_history, nearby_complaints,
                                     neighborhood_baseline, similar_violation_restaurants)}


def fn(name, desc, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": list(required)}}}


TOOL_SCHEMAS = [
    fn("get_inspection_history", "Restaurant name/cuisine/address and its prior inspections (date, type, score, grade, violations)."),
    fn("nearby_complaints", "311 complaints (Rodent, Food Poisoning, Food Establishment) near the restaurant in a window before the inspection.",
       {"radius_m": {"type": "integer", "description": "radius in meters, default 75"},
        "days": {"type": "integer", "description": "lookback days, default 90"}}),
    fn("neighborhood_baseline", "Avg score, A/B/C band counts and top violation codes for other restaurants in the same zipcode.",
       {"days": {"type": "integer", "description": "lookback days, default 365"}}),
    fn("similar_violation_restaurants", "Semantic search for past inspections with similar violations; returns their next inspection outcome.",
       {"query": {"type": "string", "description": "violation description text"}}, ["query"]),
]


def forecast(camis: str, as_of: str, verbose: bool = False) -> dict:
    mistral = clients()[1]
    tools, trace = make_tools(str(camis), as_of), []
    log = print if verbose else (lambda *a, **k: None)
    messages = [{"role": "system", "content": SYSTEM.format(as_of=as_of)},
                {"role": "user", "content": f"Forecast restaurant CAMIS {camis} for its inspection on {as_of}."}]
    log(f"\n=== Forecasting CAMIS {camis} as of {as_of} ===")
    for _ in range(MAX_ROUNDS):
        msg = mistral.chat.complete(model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
                                    tool_choice="auto", temperature=0.2,
                                    reasoning_effort="none").choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            break
        for tc in msg.tool_calls:
            name, args = tc.function.name, tc.function.arguments
            args = json.loads(args or "{}") if isinstance(args, str) else (args or {})
            try:
                data, summary = tools[name](**args)
            except Exception as e:  # feed errors back to the model instead of crashing the run
                data, summary = {"error": str(e)[:200]}, f"ERROR {str(e)[:120]}"
            trace.append({"tool": name, "args": args, "result_summary": summary})
            log(f"-> {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})\n   {summary}")
            messages.append({"role": "tool", "name": name, "tool_call_id": tc.id,
                             "content": json.dumps(data, separators=(",", ":"), default=str)})
    if isinstance(messages[-1], dict):  # rounds exhausted on a tool result; Mistral rejects user-after-tool
        messages.append({"role": "assistant", "content": "Evidence gathered."})
    messages.append({"role": "user", "content": "Give your final forecast now based on the evidence gathered. "
                     "Reply with ONE JSON object matching this schema: " + json.dumps(Forecast.model_json_schema())})
    # chat.parse breaks on Large 4 thinking chunks, so keep only text chunks and decode the first JSON object
    content = mistral.chat.complete(model=MODEL, messages=messages, tools=TOOL_SCHEMAS, tool_choice="none",
                                    response_format={"type": "json_object"}, temperature=0.1).choices[0].message.content
    text = content if isinstance(content, str) else "".join(c.text for c in content if getattr(c, "type", "") == "text")
    f = Forecast.model_validate(json.JSONDecoder().raw_decode(text[text.index("{"):])[0])
    result = f.model_dump() | {"confidence": max(0.0, min(1.0, f.confidence)), "trace": trace}
    log(f"=> {f.predicted_grade} (score {f.predicted_score}, confidence {result['confidence']:.2f})\n   {f.reasoning}")
    return result


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: python agent.py <camis> <as_of YYYY-MM-DD> [--json]")
    result = forecast(sys.argv[1], sys.argv[2], verbose=True)
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\nLikely violations:\n" + "\n".join(f"  - {v}" for v in result["likely_violations"]))
