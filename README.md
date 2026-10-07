# Inspection Forecaster

Demo video (2.5 min): https://youtu.be/irhme66ttB8

Predicts a NYC restaurant's next health inspection grade (A, B or C) before the inspector
arrives, using only evidence available before the inspection date, then backtests those
predictions against what actually happened.

Built at the Elastic x Mistral NYC Hack Night.

## What it does

Given a restaurant ID (`camis`) and a date (`as_of`), a Mistral Large 4 agent gathers evidence
from Elasticsearch through function calls and returns a predicted grade with its reasoning.
A backtest runs the agent over a stratified sample of past A, B and C inspections and compares
it to the actual grade and to a naive baseline: "same grade as last time".

## How it works

```
 NYC Open Data                       Elastic Serverless
 ------------                        ------------------------------------------------
 DOHMH inspections  --ingest.py-->   inspections     (semantic_text violations_text,
 (43nn-pn8j)                                          geo_point, grade, score, zipcode)
 311 complaints     --ingest.py-->   complaints_311  (geo_point, created_date, type)
 (erm2-nwe9)                         _inference/mistral-embeddings  (mistral-embed)
                                                ^
                                                | tool calls, all filtered to < as_of
                                                |
 python agent.py <camis> <as_of>  -->  Mistral Large 4 (function calling)
                                         - get_inspection_history
                                         - nearby_complaints
                                         - neighborhood_baseline
                                         - similar_violation_restaurants
                                                |
                                                v
                                     predicted grade + reasoning
                                                |
 python backtest.py  ---------------->  forecasts index + results.csv
                                        ES|QL: accuracy vs actual vs baseline
```

## Use of Elastic

- **Semantic search:** `violations_text` is a `semantic_text` field backed by a Mistral
  embeddings inference endpoint, so Elastic embeds at index and query time.
  `similar_violation_restaurants` finds restaurants with similar violation histories and
  what grade they got next.
- **Geo + time:** `nearby_complaints` counts 311 Rodent, Food Poisoning and Food Establishment
  complaints within 75 m of the restaurant (`geo_distance`) in the 90 days before `as_of`
  (date range), aggregated by type.
- **Aggregations / ES|QL:** `neighborhood_baseline` gets the zip code's grade mix and average
  score. The backtest summary is an ES|QL query over the `forecasts` index
  (`FROM forecasts | STATS ... BY actual_grade`).
- **Storage of results:** every forecast is written back to Elastic for inspection in Kibana.

## Use of Mistral

- **mistral-large-4** runs the agent loop with function calling: it decides which tools to call,
  in what order, and produces the final grade and explanation.
- **mistral-embed** is registered as an Elastic inference endpoint (`mistral-embeddings`) and powers
  the semantic search over violation text.

## Leakage guard

Every tool takes `as_of` and filters `inspection_date < as_of` (inspections) or
`created_date < as_of` (311). The inspection being predicted, and anything after it, is never
visible to the model. The baseline uses the same rule: the last grade before `as_of`.

## Results

Two runs, 30 stratified inspections each (10 A / 10 B / 10 C), May-Oct 2026.

| Metric                  | Agent v1 | Agent v2 (held-out) | Last grade | Last score -> band |
|-------------------------|----------|---------------------|------------|--------------------|
| Accuracy                | 28.6%    | 43.3%               | 33.3%      | 46.7%              |
| C-grade recall          | 0%       | **90%**             | 10%        | 80%                |
| Accuracy on A / B / C   |          | 10% / 30% / 90%     | 90/0/10%   | 10/50/80%          |

v1 predicted B for every actual C: it assumed restaurants improve after a bad inspection. The backtest
exposed that, so v2 adds a calibration rule (anchor on the last score; no assumed improvement) and was
re-scored on a fresh sample (different seed) to avoid tuning to the test set. v2 is a good risk detector
for C restaurants but over-flags A restaurants.

The test set is stratified (equal A/B/C), so overall accuracy is not the same as accuracy on the
real-world grade mix, which is mostly A.

## How to run

Requires Python 3.11+, an Elastic Serverless project, and a Mistral API key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install elasticsearch mistralai python-dotenv requests

./set_keys.sh                      # prompts for keys, writes .env (chmod 600)
python check.py                    # verifies Elastic + Mistral connections
python fetch.py                    # downloads inspections + 311 data to data/
python ingest.py                   # creates inference endpoint + indices, bulk loads
python agent.py <camis> <as_of>    # one forecast with tool trace, e.g. 50033403 2026-06-15
python backtest.py                 # stratified backtest -> forecasts index + results.csv
```

## Limitations

- Small backtest sample (cost and time of one LLM call chain per inspection); treat the
  numbers as indicative.
- Data window starts 2024-01-01 and is capped at 100k rows per source, so some restaurants
  have short histories.
- 311 complaints are matched by distance, not to the restaurant itself; in dense blocks a
  75 m radius covers neighbors too.
- Grades are only issued on certain inspection types; re-inspections and pending grades are
  simplified.
- No signal exists for some changes (new management, a single bad day), so those are missed.
- LLM outputs are not fully deterministic; reruns can differ.

## In Kibana

- **Dashboard** "NYC Inspection Forecaster" (`dashboard_setup.py`): backtest scoreboard vs baselines, confusion table,
  311 complaints over time and on a map, average score by borough, table of every forecast.
- **Agent Builder** agent "NYC Inspection Analyst" (`agent_builder_setup.py`): chat over the same data with
  5 custom ES|QL tools + 1 semantic search tool, running on Mistral Medium through an Elastic inference
  connector. (Large 4's thinking-chunk output isn't parsed by Agent Builder yet, so the chat agent uses Medium;
  the forecaster itself uses Large 4 directly.)
- `demo_elastic.py` walks through the Elastic queries in the terminal.
