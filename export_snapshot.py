"""Build the static snapshot the Streamlit app reads (app_data/).

Uses the raw NYC Open Data pulls in data/ (same rows ingest.py loads into Elastic),
so no API keys are needed. Run: python export_snapshot.py
"""
import os

import pandas as pd

OUT = "app_data"
os.makedirs(OUT, exist_ok=True)

# Inspections: raw data is one row per violation -> one row per inspection.
raw = pd.read_json("data/inspections.json", dtype={"camis": str, "zipcode": str})
raw["violation_description"] = raw["violation_description"].fillna("").str.slice(0, 120)
raw["address"] = (raw["building"].fillna("") + " " + raw["street"].fillna("")).str.strip()
keys = ["camis", "inspection_date"]  # same rollup as ingest.py
insp = raw.groupby(keys).agg(
    inspection_type=("inspection_type", "first"), dba=("dba", "first"), cuisine=("cuisine_description", "first"), boro=("boro", "first"),
    zipcode=("zipcode", "first"), address=("address", "first"), score=("score", "max"),
    grade=("grade", "first"), lat=("latitude", "first"), lon=("longitude", "first"),
    violations=("violation_description", lambda s: " | ".join(v for v in dict.fromkeys(s) if v)),
).reset_index()
insp["inspection_date"] = insp["inspection_date"].str.slice(0, 10)
insp = insp[insp["inspection_date"] > "1901"]  # 1900-01-01 = not yet inspected
for c in ("lat", "lon"):
    insp[c] = pd.to_numeric(insp[c], errors="coerce").round(6)
insp.loc[insp["lat"] == 0, ["lat", "lon"]] = None
cols = ["camis", "dba", "cuisine", "boro", "zipcode", "address", "inspection_date",
        "inspection_type", "score", "grade", "lat", "lon", "violations"]
insp[cols].sort_values(["camis", "inspection_date"]).to_csv(f"{OUT}/inspections.csv.gz", index=False)

# 311 complaints
c = pd.read_json("data/complaints_311.json")
c = c.rename(columns={"latitude": "lat", "longitude": "lon"})
c["created_date"] = c["created_date"].astype(str).str.slice(0, 19)
for col in ("lat", "lon"):
    c[col] = pd.to_numeric(c[col], errors="coerce").round(6)
c = c.dropna(subset=["lat", "lon"])[["created_date", "complaint_type", "descriptor", "borough", "lat", "lon"]]
path = f"{OUT}/complaints_311.csv.gz"
c.to_csv(path, index=False)
if os.path.getsize(path) > 8e6:
    c.sample(50_000, random_state=0).to_csv(path, index=False)

# Backtest forecasts
for v in ("v1", "v2"):
    r = pd.read_csv(f"results_{v}.csv", dtype={"camis": str})
    if "error" in r and r["error"].isna().all():
        r = r.drop(columns="error")
    r.to_csv(f"{OUT}/results_{v}.csv", index=False)

for f in sorted(os.listdir(OUT)):
    print(f"{f}: {os.path.getsize(f'{OUT}/{f}') / 1e6:.2f} MB")
print(f"{len(insp)} inspections, {len(c)} complaints")
