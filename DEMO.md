# Demo script (3:00)

Demo restaurant: `50033403` as of `2026-06-15` - GUIZ HOU MIAO JIA NOODLES (136-55 Roosevelt Ave,
Flushing, zip 11354, 40.760023562641, -73.828314315508). Actual: **C (score 55)**. Last score 25
(B band), no prior grade ("same as last" says A). Agent: **C**.

## Before you go on stage

- [ ] Tab 1: Kibana dashboard "NYC Inspection Forecaster", loaded, time range covers the data:
      https://nyc-hacknight-ef0767.kb.us-central1.gcp.elastic.cloud/app/dashboards#/view/inspection-forecaster
- [ ] Tab 2: Agent Builder, agent "NYC Inspection Analyst":
      https://nyc-hacknight-ef0767.kb.us-central1.gcp.elastic.cloud/app/agent_builder/agents/inspection-analyst
      **Select model "Mistral Medium (hack night)" in the chat box's model selector.** Run the demo
      question once so you know it answers in ~20 s, then start a fresh chat.
- [ ] Terminal: `cd forecaster`, `.venv` present, font size up, screen cleared. One warm-up run of
      `.venv/bin/python agent.py 50033403 2026-06-15` (~40 s).
- [ ] Backups ready: `demo_run.txt` exists; `.venv/bin/python demo_elastic.py --auto` works.
- [x] Scoreboard numbers filled in (v2 held-out run, seed 7, n=30).

---

## 0:00 - 0:40 Hook + dashboard (Kibana tab 1)

> "Everyone built chatbots on this data. We asked: can AI predict the inspection before the
> inspector arrives - and we checked."
>
> "Inspection Forecaster: a Mistral Large 4 agent that looks at a NYC restaurant the day before its
> health inspection and predicts the grade - A, B or C - using only evidence that existed before
> that day. Then we backtest it against what actually happened and write every forecast to Elastic."

Point at **"Correct predictions by actual grade"** (out of 10 per grade, agent / same-as-last-grade /
last-score):

| Actual | Agent | Same as last grade | Last score |
|--------|-------|--------------------|------------|
| A      | 1     | 9                  | 1          |
| B      | 3     | 0                  | 5          |
| C      | **9** | 1                  | 8          |

> "On the C restaurants - the ones that matter for public health - the agent catches 9 of 10."

Point at the 311 map:

> "Behind it: 100k geo-indexed 311 complaints and the DOHMH inspection history, all in Elastic."

## 0:40 - 1:40 Live agent run (terminal)

```bash
.venv/bin/python agent.py 50033403 2026-06-15
```

Narrate each tool call as it prints (~40 s total):

- **Leakage guard (say first):** "Every tool takes `as_of`. Elastic filters `inspection_date < as_of`
  and `created_date < as_of`. The model never sees the answer."
- **get_inspection_history** - "One prior inspection, score 25: B band, never graded."
- **nearby_complaints** - "A geo_distance + date-range query on 311: 9 complaints within 100 meters,
  including a food-poisoning report 8 days before the visit." (The model picks radius and window;
  read the numbers off the screen.)
- **neighborhood_baseline** - "Aggregations over zip 11354: how restaurants around it usually grade."
- **similar_violation_restaurants** (x2) - "Two semantic searches: restaurants whose violation
  history *reads* like this one, embedded with Mistral inside Elastic, and what they scored next."
- **Final answer** - read the predicted grade + one line of the reasoning.

> "Mistral Large 4 decides which tools to call and in what order - function calling, not a fixed
> pipeline. Verdict: C. Actual grade that day: C, score 55. 'Same as last time' said A."

## 1:40 - 2:30 Agent Builder (Kibana tab 2)

(Model already set to "Mistral Medium (hack night)".) Type:

> Which restaurants did the forecaster correctly flag as C?

While it runs (~20 s):

> "Same data, now for an analyst. This is Elastic Agent Builder: an agent with our custom ES|QL tools
> over the inspections, 311 and forecasts indices, plus a semantic search tool on violation text.
> The model is Mistral, wired in through an Elastic inference connector - no glue code."

When it answers, point at one restaurant name and its tool calls in the trace.

## 2:30 - 3:00 What we learned + close

> "v1 of the agent lost to a dumb baseline: it caught zero of the C restaurants because it assumed
> everyone cleans up after a bad inspection. The backtest told us why, we added that calibration,
> and re-tested on a fresh sample it had never seen. v2, 30 held-out inspections: 9 of 10 C's,
> versus 1 of 10 for 'same grade as last time' and 8 of 10 for 'last score'."
>
> "Honest trade-off: overall accuracy is 43% vs 47% for the best baseline, because it over-flags A's.
> It's a risk detector, not a grade predictor - and n=30 is tonight's sample, not a paper."
>
> "Why it matters: DOHMH has a limited number of inspectors, and a missed C costs more than a false
> alarm. A forecast like this ranks where to go first. And the pattern isn't about restaurants - any
> events-plus-locations data, like work orders, claims or sensor alerts, drops in: Elastic for geo,
> time and semantic retrieval, Mistral to reason over it, and a backtest to prove it."

---

## Backup plan

- **Live agent hangs > 20 s:** "Live API is slow - here's the same run from earlier," `Ctrl-C`,
  `cat demo_run.txt`, then `grep 50033403 results.csv`.
- **Kibana fails:** `.venv/bin/python demo_elastic.py --auto` runs the Elastic queries in the terminal.
  Read the scoreboard off the table above.

## Likely judge questions

- **"How do you know there's no leakage?"** Every tool filters `< as_of` in the Elastic query
  itself, not in the prompt. The baseline uses the same rule (last grade before `as_of`).
- **"Why Medium in Agent Builder but Large 4 in the forecaster?"** Large 4 returns thinking chunks
  that Agent Builder doesn't parse yet, so the chat agent uses Medium through the same connector. The
  forecaster calls Large 4 directly.
- **"n=30 is tiny."** Agreed - cost and time of one LLM tool chain per inspection. Stratified 10/10/10
  so C's are represented; the real mix is mostly A, so overall accuracy won't transfer. v2 was scored
  on a different seed than the one we calibrated on.
- **"Why optimize for recall on C?"** C restaurants are the public-health risk. Inspectors have
  limited visits; a false alarm costs one visit, a missed C leaves a risky kitchen open. Next step: a
  confidence threshold to trade recall for precision.

---

## Appendix: Elastic queries (backup)

Paste into Kibana Dev Tools if you need to show raw queries.

**1. Mistral lives inside Elastic** - the embedding model is an Elastic inference endpoint.

```
GET _inference/mistral-embeddings
```

**2. semantic_text mapping** - Elastic calls Mistral at index and query time.

```
GET inspections/_mapping
```

**3. Semantic query** - plain-English search over violation histories.

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

**4a. Restaurant's point** (setup).

```
GET inspections/_search
{
  "size": 1,
  "_source": ["dba", "address", "zipcode", "location"],
  "query": { "term": { "camis": "50033403" } }
}
```

**4b. geo_distance + date-range 311 aggregation.**

```
GET complaints_311/_search
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "geo_distance": { "distance": "100m", "location": { "lat": 40.760023562641, "lon": -73.828314315508 } } },
        { "range": { "created_date": { "gte": "2026-06-15||-180d", "lt": "2026-06-15" } } }
      ]
    }
  },
  "aggs": {
    "by_type": { "terms": { "field": "complaint_type" } },
    "per_week": { "date_histogram": { "field": "created_date", "calendar_interval": "week" } }
  }
}
```

**5. Neighborhood baseline in ES|QL.**

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

**6. Scoreboard** - expected (v2): A 0.1 / 0.9 / 0.1, B 0.3 / 0.0 / 0.5, C **0.9** / 0.1 / 0.8.

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
