"""Download raw NYC data to data/*.json (no keys needed)."""
import json
import os
import requests

os.makedirs("data", exist_ok=True)


def get(url, params, out):
    rows = requests.get(url, params=params, timeout=300).json()
    json.dump(rows, open(f"data/{out}", "w"))
    print(out, len(rows))


# Restaurant inspections, one row per violation line
get("https://data.cityofnewyork.us/resource/43nn-pn8j.json", {
    "$limit": 100000,
    "$order": "inspection_date DESC",
    "$where": "inspection_date > '2024-01-01' AND camis IS NOT NULL AND latitude IS NOT NULL",
}, "inspections.json")

# 311 complaints that could foreshadow a bad inspection
get("https://data.cityofnewyork.us/resource/erm2-nwe9.json", {
    "$limit": 100000,
    "$order": "created_date DESC",
    "$select": "unique_key,created_date,complaint_type,descriptor,incident_address,borough,latitude,longitude",
    "$where": "complaint_type in('Rodent','Food Poisoning','Food Establishment','Unsanitary Condition') "
              "AND created_date > '2024-01-01' AND latitude IS NOT NULL",
}, "complaints_311.json")
