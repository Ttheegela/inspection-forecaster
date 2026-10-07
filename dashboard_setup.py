"""Create/overwrite the "NYC Inspection Forecaster" Kibana dashboard (idempotent, fixed ids)."""
import json
import os

import requests
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv(".env")
KB = os.environ["ES_URL"].replace(".es.", ".kb.")
H = {"Authorization": f"ApiKey {os.environ['ES_API_KEY']}", "kbn-xsrf": "true"}
DASH_ID = "inspection-forecaster"


def call(method, path, **kw):
    r = requests.request(method, KB + path, headers=H, timeout=60, **kw)
    if not r.ok:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
    return r


# ---------- data views ----------
DATA_VIEWS = [
    {"id": "dv-inspections", "title": "inspections", "name": "Inspections"},
    {"id": "dv-complaints", "title": "complaints_311", "name": "311 complaints", "timeFieldName": "created_date"},
    {"id": "dv-forecasts", "title": "forecasts", "name": "Forecasts", "runtimeFieldMap": {
        "score_baseline_correct": {"type": "boolean", "script": {"source":
            "emit(doc['score_baseline_grade'].size() > 0 && doc['actual_grade'].size() > 0 "
            "&& doc['score_baseline_grade'].value == doc['actual_grade'].value)"}}}},
]


# ---------- Lens column helpers ----------
def terms(field, label, size=10, alpha=True):
    order = {"type": "alphabetical", "fallback": True} if alpha else {"type": "column", "columnId": "m"}
    return {"label": label, "customLabel": True, "dataType": "string", "operationType": "terms",
            "sourceField": field, "isBucketed": True, "scale": "ordinal",
            "params": {"size": size, "orderBy": order, "orderDirection": "asc" if alpha else "desc",
                       "otherBucket": False, "missingBucket": False}}


def count(label, kql=None):
    col = {"label": label, "customLabel": True, "dataType": "number", "operationType": "count",
           "sourceField": "___records___", "isBucketed": False, "scale": "ratio"}
    if kql:
        col["filter"] = {"query": kql, "language": "kuery"}
    return col


def lens(id_, title, dv, vis_type, columns, visualization):
    # migration version is required: without it Kibana runs 7.x lens migrations on formBased state and 500s
    return {"type": "lens", "id": id_, "typeMigrationVersion": "8.9.0", "coreMigrationVersion": "8.8.0",
            "attributes": {
        "title": title, "visualizationType": vis_type,
        "state": {"datasourceStates": {"formBased": {"layers": {"L1": {
                      "columns": columns, "columnOrder": list(columns), "incompleteColumns": {}}}}},
                  "visualization": visualization, "query": {"query": "", "language": "kuery"}, "filters": []}},
        "references": [{"type": "index-pattern", "id": dv, "name": "indexpattern-datasource-layer-L1"}]}


def xy(series, x, accessors, split=None):
    layer = {"layerId": "L1", "layerType": "data", "seriesType": series, "xAccessor": x, "accessors": accessors}
    if split:
        layer["splitAccessor"] = split
    return {"legend": {"isVisible": True, "position": "right"}, "preferredSeriesType": series,
            "valueLabels": "show", "layers": [layer]}


MARKDOWN = """## NYC Inspection Forecaster
An AI agent built on Elasticsearch predicts the grade a NYC restaurant will get on its *next* health inspection,
using its inspection history (27,830 inspections), nearby 311 rodent / food-poisoning complaints (100k), and semantic
search over violation text. Backtested on 30 restaurants (10 each actual A / B / C).

**Headline:** the v2 agent catches **9 of 10 C restaurants** vs **1/10** (last-grade baseline) and **8/10** (score baseline);
overall accuracy **43%** vs **47%**. It trades A-grade accuracy for flagging the restaurants that actually fail.
"""

OBJECTS = [
    {"type": "visualization", "id": "if-header", "attributes": {
        "title": "Project overview", "description": "", "uiStateJSON": "{}",
        "visState": json.dumps({"title": "Project overview", "type": "markdown", "aggs": [],
                                "params": {"markdown": MARKDOWN, "fontSize": 12, "openLinksInNewTab": False}}),
        "kibanaSavedObjectMeta": {"searchSourceJSON": "{}"}}, "references": []},

    lens("if-accuracy", "Correct predictions by actual grade (out of 10)", "dv-forecasts", "lnsXY",
         {"x": terms("actual_grade", "Actual grade"),
          "m1": count("AI agent v2", "correct:true"),
          "m2": count("Baseline: last grade", "baseline_correct:true"),
          "m3": count("Baseline: score-based", "score_baseline_correct:true")},
         {**xy("bar", "x", ["m1", "m2", "m3"]), "yTitle": "Correct (of 10)"}),

    lens("if-confusion", "Agent confusion: predicted (rows) vs actual (columns)", "dv-forecasts", "lnsDatatable",
         {"r": terms("predicted_grade", "Predicted"), "c": terms("actual_grade", "Actual"), "m": count("Restaurants")},
         {"layerId": "L1", "layerType": "data",
          "columns": [{"columnId": "r"}, {"columnId": "c", "isTransposed": True}, {"columnId": "m"}]}),

    lens("if-complaints-time", "311 complaints over time by type", "dv-complaints", "lnsXY",
         {"x": {"label": "Created", "customLabel": True, "dataType": "date", "operationType": "date_histogram",
                "sourceField": "created_date", "isBucketed": True, "scale": "interval",
                "params": {"interval": "M", "includeEmptyRows": True}},
          "s": terms("complaint_type", "Complaint type", 5, alpha=False),
          "m": count("Complaints")},
         {**xy("bar_stacked", "x", ["m"], split="s"), "valueLabels": "hide"}),

    lens("if-score-boro", "Average inspection score by borough (higher = worse)", "dv-inspections", "lnsXY",
         {"x": terms("boro", "Borough", 10, alpha=False),
          "m": {"label": "Avg score", "customLabel": True, "dataType": "number", "operationType": "average",
                "sourceField": "score", "isBucketed": False, "scale": "ratio"}},
         xy("bar", "x", ["m"])),

    {"type": "map", "id": "if-complaints-map", "attributes": {
        "title": "311 complaints map", "description": "", "uiStateJSON": json.dumps({"isLayerTOCOpen": False}),
        "mapStateJSON": json.dumps({"zoom": 9.8, "center": {"lon": -73.94, "lat": 40.71},
                                    "timeFilters": {"from": "now-3y", "to": "now"},
                                    "refreshConfig": {"isPaused": True, "interval": 0},
                                    "query": {"query": "", "language": "kuery"}, "filters": []}),
        "layerListJSON": json.dumps([
            {"id": "basemap", "type": "EMS_VECTOR_TILE", "visible": True, "alpha": 1,
             "sourceDescriptor": {"type": "EMS_TMS", "isAutoSelect": True, "lightModeDefault": "road_map_desaturated"},
             "style": {"type": "EMS_VECTOR_TILE"}},
            {"id": "complaints", "type": "MVT_VECTOR", "label": "311 complaints", "visible": True, "alpha": 0.75,
             "sourceDescriptor": {"type": "ES_SEARCH", "id": "complaints-src", "geoField": "location",
                                  "indexPatternRefName": "layer_1_source_index_pattern", "scalingType": "MVT",
                                  "applyGlobalQuery": True, "applyGlobalTime": True,
                                  "tooltipProperties": ["complaint_type", "descriptor", "borough", "created_date"]},
             "style": {"type": "VECTOR", "properties": {
                 "fillColor": {"type": "DYNAMIC", "options": {"field": {"name": "complaint_type", "origin": "source"},
                                                              "type": "CATEGORICAL", "colorCategory": "palette_0"}},
                 "lineColor": {"type": "STATIC", "options": {"color": "#FFFFFF"}},
                 "lineWidth": {"type": "STATIC", "options": {"size": 0}},
                 "iconSize": {"type": "STATIC", "options": {"size": 3}}}}},
        ])},
     "references": [{"name": "layer_1_source_index_pattern", "type": "index-pattern", "id": "dv-complaints"}]},

    {"type": "search", "id": "if-forecasts-table", "attributes": {
        "title": "Forecast backtest results", "description": "",
        "columns": ["dba", "as_of", "actual_grade", "predicted_grade", "confidence", "correct",
                    "baseline_grade", "score_baseline_grade"],
        "sort": [["actual_grade", "desc"]], "grid": {}, "hideChart": True, "isTextBasedQuery": False,
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({
            "query": {"query": "", "language": "kuery"}, "filter": [],
            "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index"})}},
     "references": [{"name": "kibanaSavedObjectMeta.searchSourceJSON.index", "type": "index-pattern",
                     "id": "dv-forecasts"}]},
]

# (object id, x, y, w, h) on a 48-col grid
LAYOUT = [("if-header", 0, 0, 48, 9), ("if-accuracy", 0, 9, 24, 14), ("if-confusion", 24, 9, 24, 14),
          ("if-complaints-time", 0, 23, 24, 15), ("if-complaints-map", 24, 23, 24, 15),
          ("if-score-boro", 0, 38, 16, 15), ("if-forecasts-table", 16, 38, 32, 15)]


def dashboard():
    types = {o["id"]: o["type"] for o in OBJECTS}
    panels, refs = [], []
    for i, (oid, x, y, w, h) in enumerate(LAYOUT, 1):
        p = f"p{i}"
        panels.append({"type": types[oid], "panelIndex": p, "gridData": {"x": x, "y": y, "w": w, "h": h, "i": p},
                       "embeddableConfig": {}, "panelRefName": f"panel_{p}"})
        refs.append({"name": f"{p}:panel_{p}", "type": types[oid], "id": oid})
    return {"type": "dashboard", "id": DASH_ID, "references": refs, "attributes": {
        "title": "NYC Inspection Forecaster",
        "description": "AI forecaster for NYC restaurant inspection grades: backtest results + 311 / inspection context.",
        "panelsJSON": json.dumps(panels), "optionsJSON": json.dumps({"useMargins": True, "hidePanelTitles": False}),
        "timeRestore": True, "timeFrom": "now-3y", "timeTo": "now",
        "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(
            {"query": {"query": "", "language": "kuery"}, "filter": []})}}}


# ES|QL equivalents of each panel, run against ES to prove fields exist and data is non-empty
CHECKS = {
    "accuracy": "FROM forecasts | STATS agent=SUM(CASE(correct,1,0)), last_grade=SUM(CASE(baseline_correct,1,0)), "
                "score_base=SUM(CASE(score_baseline_grade==actual_grade,1,0)) BY actual_grade | SORT actual_grade",
    "confusion": "FROM forecasts | STATS n=COUNT(*) BY predicted_grade, actual_grade | SORT predicted_grade, actual_grade",
    "complaints_time": "FROM complaints_311 | STATS n=COUNT(*) BY complaint_type",
    "score_boro": "FROM inspections | STATS avg=AVG(score) BY boro | SORT avg DESC",
    "map": "FROM complaints_311 | WHERE location IS NOT NULL | STATS n=COUNT(*)",
    "table": "FROM forecasts | KEEP dba, as_of, actual_grade, predicted_grade, confidence | LIMIT 3",
}


def main():
    for dv in DATA_VIEWS:
        call("POST", "/api/data_views/data_view", json={"data_view": dv, "override": True})
    print("data views ok:", [d["id"] for d in DATA_VIEWS])

    ndjson = "\n".join(json.dumps(o) for o in OBJECTS + [dashboard()]) + "\n"
    res = call("POST", "/api/saved_objects/_import?overwrite=true",
               files={"file": ("dashboard.ndjson", ndjson.encode())}).json()
    if not res.get("success"):
        raise SystemExit(f"import failed: {json.dumps(res.get('errors'), indent=1)}")
    print(f"imported {res['successCount']} objects", res.get("warnings") or "")

    # verify: dashboard readable, export with deep refs has no missing references
    call("GET", f"/api/dashboards/{DASH_ID}")
    exp = call("POST", "/api/saved_objects/_export", json={
        "objects": [{"type": "dashboard", "id": DASH_ID}], "includeReferencesDeep": True}).text.strip().splitlines()
    details = json.loads(exp[-1])
    print("export:", details.get("exportedCount"), "objects, missing refs:", details.get("missingRefCount"))
    assert details.get("missingRefCount") == 0, details.get("missingReferences")

    es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"])
    for name, q in CHECKS.items():
        r = es.esql.query(query=q + ("" if "LIMIT" in q else " | LIMIT 100"))
        assert r["values"], f"{name}: no rows"
        print(f"check {name}: {r['values'][:6]}")
    print(f"\nDashboard: {KB}/app/dashboards#/view/{DASH_ID}")


if __name__ == "__main__":
    main()
