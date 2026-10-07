"""Backtest the Inspection Forecaster against real NYC inspections.

For each test inspection (>= 2026-05-01, graded A/B/C, restaurant has prior history)
we ask the agent to forecast as of the inspection date (it may only use earlier evidence)
and compare against two naive baselines.

    python backtest.py --n 30          # full run (Mistral calls)
    python backtest.py --dry-run       # test-set selection + baselines only
"""
import argparse
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers

TEST_START = "2026-05-01"
SEED = 42
GRADES = ["A", "B", "C"]
STOP = {"with", "from", "that", "this", "were", "have", "food", "other", "than", "into", "within",
        "area", "areas", "used", "provided", "properly", "maintained", "present", "observed", "and", "the", "not"}

FORECAST_MAPPING = {
    "camis": {"type": "keyword"}, "dba": {"type": "keyword"}, "as_of": {"type": "date"},
    "actual_grade": {"type": "keyword"}, "actual_score": {"type": "integer"},
    "predicted_grade": {"type": "keyword"}, "predicted_score": {"type": "float"},
    "baseline_grade": {"type": "keyword"}, "score_baseline_grade": {"type": "keyword"},
    "correct": {"type": "boolean"}, "baseline_correct": {"type": "boolean"},
    "violation_hit": {"type": "boolean"}, "confidence": {"type": "keyword"},
    "reasoning": {"type": "text"}, "likely_violations": {"type": "text"},
}


def score_band(score):
    """NYC grading bands: 0-13 A, 14-27 B, 28+ C."""
    if pd.isna(score):
        return "A"
    return "A" if score <= 13 else "B" if score <= 27 else "C"


def words(text):
    return {w for w in re.findall(r"[a-z]+", str(text).lower()) if len(w) > 3 and w not in STOP}


def violation_hit(predicted, actual):
    """Any predicted violation shares >=2 content words (or its only word) with any actual one."""
    # ponytail: keyword overlap, swap for semantic similarity via the mistral-embeddings endpoint if it matters
    for p in predicted or []:
        pw = words(p)
        need = min(2, len(pw))
        if need and any(len(pw & words(a)) >= need for a in actual or []):
            return True
    return False


def load_inspections(es):
    src = ["camis", "dba", "inspection_date", "grade", "score", "violations"]
    rows = [h["_source"] for h in helpers.scan(es, index="inspections", query={"_source": src, "query": {"match_all": {}}})]
    return pd.DataFrame(rows, columns=src)


def select_test_set(df, n, seed=SEED):
    df = df.copy()
    df["camis"] = df["camis"].astype(str)
    df["inspection_date"] = df["inspection_date"].astype(str).str[:10]
    df = df.sort_values(["camis", "inspection_date"]).reset_index(drop=True)
    by = df["camis"]
    df["has_prior"] = df.groupby("camis").cumcount() > 0
    graded = df["grade"].where(df["grade"].isin(GRADES))
    df["baseline_grade"] = graded.groupby(by).shift().groupby(by).ffill().fillna("A")
    prev_score = df["score"].groupby(by).shift().groupby(by).ffill()
    df["score_baseline_grade"] = prev_score.map(score_band)

    pool = df[(df["inspection_date"] >= TEST_START) & df["grade"].isin(GRADES) & df["has_prior"]]
    print(f"Test pool: {len(pool)} graded inspections since {TEST_START} with prior history")
    print("  natural grade mix:", pool["grade"].value_counts().reindex(GRADES, fill_value=0).to_dict())
    parts = []
    for i, g in enumerate(GRADES):
        k = n // 3 + (1 if i < n % 3 else 0)
        sub = pool[pool["grade"] == g]
        parts.append(sub.sample(min(k, len(sub)), random_state=seed))
    test = pd.concat(parts).reset_index(drop=True)
    print("  sampled grade mix:", test["grade"].value_counts().reindex(GRADES, fill_value=0).to_dict(),
          "(stratified: C is deliberately OVERSAMPLED vs reality so C-recall is measurable)")
    return test


def run_one(forecast, row):
    for attempt in range(4):
        try:
            return forecast(row["camis"], row["inspection_date"]), None
        except Exception as e:  # keep going on any agent failure
            msg = str(e)
            if attempt < 3 and ("429" in msg or "rate" in msg.lower()):
                time.sleep(2 ** (attempt + 1))
                continue
            return None, f"{type(e).__name__}: {msg[:200]}"


def run_agent(test):
    from agent import forecast  # imported lazily so --dry-run works without the agent
    out = [None] * len(test)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(run_one, forecast, row): i for i, row in test.iterrows()}
        for done, fut in enumerate(as_completed(futs), 1):
            i = futs[fut]
            res, err = fut.result()
            row = test.loc[i]
            pred = str((res or {}).get("predicted_grade", "")).strip().upper()[:1] or None
            print(f"  [{done}/{len(test)}] {row['dba']!s:30.30} actual={row['grade']} "
                  f"agent={pred or 'ERR'} baseline={row['baseline_grade']}" + (f"  !! {err}" if err else ""))
            out[i] = {"res": res, "err": err, "pred": pred}
    return out


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build_results(test, outs):
    recs = []
    for (_, row), o in zip(test.iterrows(), outs):
        res = o["res"] or {}
        likely = res.get("likely_violations") or []
        recs.append({
            "camis": row["camis"], "dba": row["dba"], "as_of": row["inspection_date"],
            "actual_grade": row["grade"], "actual_score": None if pd.isna(row["score"]) else int(row["score"]),
            "predicted_grade": o["pred"], "predicted_score": to_float(res.get("predicted_score")),
            "baseline_grade": row["baseline_grade"], "score_baseline_grade": row["score_baseline_grade"],
            "correct": o["pred"] == row["grade"], "baseline_correct": row["baseline_grade"] == row["grade"],
            "violation_hit": violation_hit(likely, row["violations"]),
            "confidence": None if res.get("confidence") is None else str(res.get("confidence")),
            "reasoning": res.get("reasoning"), "likely_violations": likely, "error": o["err"],
        })
    return pd.DataFrame(recs)


def write_es(es, ok):
    if es.indices.exists(index="forecasts"):
        es.indices.delete(index="forecasts")
    es.indices.create(index="forecasts", mappings={"properties": FORECAST_MAPPING})
    docs = ok.drop(columns=["error"]).astype(object).where(ok.notna(), None).to_dict("records")
    n, errs = helpers.bulk(es, ({"_index": "forecasts", "_id": f"{d['camis']}_{d['as_of']}", "_source": d} for d in docs),
                           raise_on_error=False)
    es.indices.refresh(index="forecasts")
    print(f"Wrote {n} docs to ES index 'forecasts' ({len(errs)} errors)")


def esql_summary(es):
    q = ("FROM forecasts | STATS n = COUNT(*), agent_acc = AVG(CASE(correct, 1.0, 0.0)), "
         "base_acc = AVG(CASE(baseline_correct, 1.0, 0.0)) BY actual_grade | SORT actual_grade")
    print("\nES|QL >", q)
    try:
        print(es.esql.query(query=q, format="txt").body)
    except Exception as e:
        print("  ES|QL failed:", str(e)[:200])


def pct(x):
    return "  n/a" if pd.isna(x) else f"{100 * x:5.1f}%"


def baseline_report(test):
    acc = (test["baseline_grade"] == test["grade"]).mean()
    sacc = (test["score_baseline_grade"] == test["grade"]).mean()
    c = test[test["grade"] == "C"]
    print(f"\nBaseline 'same as last grade'   accuracy {pct(acc)}  C-recall {pct((c['baseline_grade'] == 'C').mean())}")
    print(f"Baseline 'last score -> band'   accuracy {pct(sacc)}  C-recall {pct((c['score_baseline_grade'] == 'C').mean())}")
    print("\nBaseline confusion (rows=actual, cols=predicted):")
    print(pd.crosstab(test["grade"], test["baseline_grade"], rownames=["actual"], colnames=["baseline"]))


def scoreboard(res):
    ok = res[res["error"].isna() & res["predicted_grade"].isin(GRADES)]
    c = ok[ok["actual_grade"] == "C"]
    rows = [
        ("Accuracy", ok["correct"].mean(), ok["baseline_correct"].mean(), (ok["score_baseline_grade"] == ok["actual_grade"]).mean()),
        ("C-grade recall", (c["predicted_grade"] == "C").mean(), (c["baseline_grade"] == "C").mean(), (c["score_baseline_grade"] == "C").mean()),
    ]
    print("\nAgent confusion (rows=actual, cols=predicted):")
    print(pd.crosstab(ok["actual_grade"], ok["predicted_grade"], rownames=["actual"], colnames=["agent"]))
    print("\n" + "=" * 64)
    print(f" INSPECTION FORECASTER BACKTEST   {len(ok)}/{len(res)} forecasts ok, {len(res) - len(ok)} failed")
    print("=" * 64)
    print(f" {'metric':<18}{'agent':>12}{'last grade':>14}{'last score':>14}")
    for name, a, b, s in rows:
        print(f" {name:<18}{pct(a):>12}{pct(b):>14}{pct(s):>14}")
    print(f" {'Violation hit rate':<18}{pct(ok['violation_hit'].mean()):>12}   (>=1 predicted violation matched)")
    print(f" C cases in sample: {len(c)}  (C oversampled on purpose; real-world C rate is far lower)")
    print("=" * 64)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=SEED, help="new seed = fresh held-out sample")
    ap.add_argument("--dry-run", action="store_true", help="test-set selection + baselines only, no Mistral calls")
    args = ap.parse_args()

    load_dotenv()
    es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=120)
    test = select_test_set(load_inspections(es), args.n, args.seed)
    baseline_report(test)
    if args.dry_run:
        print(test[["camis", "dba", "inspection_date", "grade", "score", "baseline_grade", "score_baseline_grade"]].to_string())
        return

    print(f"\nForecasting {len(test)} inspections with the agent (6 workers)...")
    res = build_results(test, run_agent(test))
    res.to_csv("results.csv", index=False)
    print("Saved results.csv")
    ok = scoreboard(res)
    if len(ok):
        write_es(es, ok)
        esql_summary(es)


assert score_band(13) == "A" and score_band(14) == "B" and score_band(28) == "C" and score_band(None) == "A"
assert violation_hit(["Evidence of mice or live mice"], ["Evidence of mice or live mice present in facility's food areas."])
assert not violation_hit(["Hot food held below 140F"], ["Evidence of mice"])

if __name__ == "__main__":
    main()
