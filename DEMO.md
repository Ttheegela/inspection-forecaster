# Demo script (3:00)

## Before you go on stage

- [ ] Terminal: `cd forecaster && source .venv/bin/activate`, font size up, screen cleared.
- [ ] Pick the demo restaurant from `results.csv`: a row where the agent was right and the
      baseline was wrong (e.g. last grade A, actual B, agent said B). Fill in below:
      `50033403` = 50033403  `2026-06-15` = 2026-06-15  `<DBA>` = GUIZ HOU MIAO JIA NOODLES (136-55 Roosevelt Ave, Flushing)
      `11354` = 11354  `40.760023562641,-73.828314315508` = 40.760023562641, -73.828314315508
      Actual: C (score 55). Last score 25 (B band), no prior grade ("same as last" says A). Agent: C.
- [ ] Do one warm-up run of `python agent.py 50033403 2026-06-15` so you know how long it takes.
- [ ] Kibana Dev Tools open, all snippets below pasted in, placeholders filled, each run once.
- [ ] Second tab: `results.csv` open (backup), Discover on `forecasts` (backup).
- [x] Scoreboard numbers filled in (v2 held-out run, seed 7, n=30).

---

## 0:00 - 0:20 Hook (talk, terminal visible)

> "Everyone built chatbots on this data. We asked: can AI predict the inspection before the
> inspector arrives - and we checked."
>
> "Inspection Forecaster: a Mistral Large agent that looks at a NYC restaurant the day before its
> health inspection and predicts the grade - A, B or C - using only evidence that existed before
> that day. Then we backtest it against what actually happened."

## 0:20 - 1:10 Live agent run (terminal)

Type:

```bash
python agent.py 50033403 2026-06-15
```

Narrate each tool call as it prints:

- **Leakage guard (say first):** "Every tool takes `as_of`. Elastic filters `inspection_date < as_of`
  and `created_date < as_of`. The model never sees the answer."
- **get_inspection_history** - "Its past inspections from Elastic: scores, grades, violation codes."
- **nearby_complaints** - "A geo_distance query: 311 rodent, food-poisoning and food-establishment
  complaints within 75 meters in the 90 days before the inspection."
- **neighborhood_baseline** - "Aggregations over the zip code: how restaurants around it usually grade."
- **similar_violation_restaurants** - "Semantic search: restaurants whose violation history *reads*
  like this one, embedded with Mistral, and what grade they got next."
- **Final answer** - read the predicted grade + one line of the reasoning.

> "Mistral Large 4 decides which tools to call and in what order - that's function calling,
> not a fixed pipeline. Actual grade that day: C, score 55. Its last score was 25, so both simple baselines
> said A or B. The agent caught a food-poisoning complaint 100m away 8 days before the visit."

## 1:10 - 2:05 Elastic under the hood (Kibana Dev Tools)

Click through the pre-run snippets, ~10 s each. One sentence per snippet.

**1. Mistral lives inside Elastic** - "The embedding model is an Elastic inference endpoint."

```
GET _inference/mistral-embeddings
```

**2. semantic_text mapping** - "Violation text is a `semantic_text` field; Elastic calls Mistral at
index and query time, no vector plumbing in our code."

```
GET inspections/_mapping
```

**3. Semantic query** - "Plain-English search over violation histories."

```
GET inspections/_search
{
  "size": 5,
  "_source": ["dba", "grade", "score", "inspection_date", "zipcode"],
  "query": {
    "semantic": {
      "field": "violations_text",
      "query": "mice droppings and flies near food prep, cold food held too warm"
    }
  }
}
```

**4a. (setup, pre-run, don't show)** - get the restaurant's point.

```
GET inspections/_search
{
  "size": 1,
  "_source": ["dba", "address", "zipcode", "location"],
  "query": { "term": { "camis": "50033403" } }
}
```

**4b. geo_distance + date-range 311 aggregation** - "What the neighbors reported in the 90 days
before the inspector showed up, within 75 meters."

```
GET complaints_311/_search
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "geo_distance": { "distance": "75m", "location": { "lat": 40.760023562641, "lon": -73.828314315508 } } },
        { "range": { "created_date": { "gte": "2026-06-15||-90d", "lt": "2026-06-15" } } }
      ]
    }
  },
  "aggs": {
    "by_type": { "terms": { "field": "complaint_type" } },
    "per_week": { "date_histogram": { "field": "created_date", "calendar_interval": "week" } }
  }
}
```

**5. Neighborhood baseline in ES|QL** - "Zip-code grade mix, also before the as-of date."

```
POST _query?format=txt
{
  "query": """
    FROM inspections
    | WHERE zipcode == "11354" AND inspection_date < "2026-06-15" AND grade IS NOT NULL
    | STATS n = COUNT(*), avg_score = AVG(score) BY grade
    | SORT grade
  """
}
```

## 2:05 - 2:35 Scoreboard (Dev Tools)

> "One example proves nothing. So we ran a backtest on a stratified set of A, B and C inspections
> and wrote every forecast back into an Elastic index."

```
POST _query?format=txt
{
  "query": """
    FROM forecasts
    | EVAL agent_hit = CASE(predicted_grade == actual_grade, 1, 0),
           last_grade_hit = CASE(baseline_grade == actual_grade, 1, 0),
           last_score_hit = CASE(score_baseline_grade == actual_grade, 1, 0)
    | STATS n = COUNT(*), agent = AVG(agent_hit), last_grade = AVG(last_grade_hit), last_score = AVG(last_score_hit) BY actual_grade
    | SORT actual_grade
  """
}
```

Expected (v2): A 0.1 / 0.9 / 0.1, B 0.3 / 0.0 / 0.5, C **0.9** / 0.1 / 0.8.

> "v1 of the agent lost to a dumb baseline: it caught zero of the C restaurants because it assumed
> everyone cleans up after a bad inspection. The backtest told us why, we added that calibration,
> and re-tested on a fresh sample it had never seen."
>
> "v2, 30 held-out inspections: it catches 9 of 10 C restaurants, the ones that matter for public
> health, versus 1 of 10 for 'same grade as last time' and 8 of 10 for 'last score'. The trade-off is
> honest: overall accuracy is 43% vs 47% for the best baseline, because it flags too many A's as risky.
> For an inspector deciding where to go first, a missed C costs more than a false alarm."

## 2:35 - 2:50 Honest framing

> "Caveats: 30 is small - this is tonight's sample, not a paper. Grades are stratified, so the
> real-world mix is mostly A. It over-flags A restaurants (1 of 10 right) - it is tuned to be a risk detector, not a
> grade predictor. Next step: a confidence threshold to trade recall for precision."

## 2:50 - 3:00 Close

> "Why it matters: DOHMH has a limited number of inspectors. A forecast like this could rank which
> restaurants to visit first. And the pattern isn't about restaurants - any customer with events
> plus locations, like work orders, claims, or sensor alerts, can drop it in: Elastic for geo,
> time and semantic retrieval, Mistral to reason over it, and a backtest to prove it."

---

## Backup plan (if the live call fails or hangs > 20 s)

1. Say: "Live API is slow - here's the same run from earlier," and `Ctrl-C`.
2. Show the saved trace: `cat demo_run.txt` (record it during setup with
   `python agent.py 50033403 2026-06-15 | tee demo_run.txt`).
3. Show the row for that restaurant: `grep 50033403 results.csv`.
4. If Elastic is also down: open `results.csv` and read the accuracy off it
   (`python -c "import pandas as pd; d=pd.read_csv('results.csv'); print(len(d))"` or just scroll).
5. Kibana Discover on `forecasts` shows the same rows as the ES|QL query.
