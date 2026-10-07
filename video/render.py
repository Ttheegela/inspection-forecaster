"""Render the demo video scenes as 1920x1080 PNGs into video/frames/."""
import os, json, re, textwrap
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "frames"); os.makedirs(OUT, exist_ok=True)
load_dotenv(os.path.join(ROOT, ".env"))

BG, FG, MUTED = "#0f1419", "#e6edf3", "#8b98a5"
ORANGE, TEAL, BLUE, RED, YELLOW, GREEN = "#ff7000", "#00bfb3", "#4c9aff", "#f2545b", "#f5c542", "#3fb950"
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FG, "axes.labelcolor": FG,
                     "xtick.color": FG, "ytick.color": FG, "axes.edgecolor": MUTED})


def canvas():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1920); ax.set_ylim(1080, 0); ax.axis("off")
    return fig, ax


def header(ax, title, sub=None):
    ax.text(90, 95, title, fontsize=46, weight="bold", va="center")
    if sub: ax.text(92, 160, sub, fontsize=24, color=MUTED, va="center")
    ax.plot([90, 1830], [200, 200], color="#253040", lw=2)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), facecolor=BG); plt.close(fig)


def box(ax, x, y, w, h, text, color, fs=22):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=18",
                                fc="#18212b", ec=color, lw=3))
    ax.text(x + w / 2, y + h / 2, text, fontsize=fs, ha="center", va="center", linespacing=1.5)


def arrow(ax, a, b, color=MUTED):
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", lw=3, color=color, mutation_scale=28))


# 1. Title
fig, ax = canvas()
ax.text(960, 420, "Inspection Forecaster", fontsize=92, weight="bold", ha="center", va="center")
ax.text(960, 560, "Can AI predict a NYC restaurant's health grade\nbefore the inspector arrives?",
        fontsize=38, ha="center", va="center", linespacing=1.4)
ax.text(960, 720, "Elastic  x  Mistral   NYC Hack Night", fontsize=30, color=ORANGE, ha="center", va="center")
ax.text(960, 800, "Mistral Large 4 agent  -  Elasticsearch evidence  -  honest backtest",
        fontsize=24, color=MUTED, ha="center", va="center")
save(fig, "01.png")

# 2. Architecture
fig, ax = canvas()
header(ax, "How it works", "Every tool filters to evidence dated before the inspection (date < as_of)")
box(ax, 90, 330, 380, 220, "NYC Open Data\n\nDOHMH inspections\n311 complaints", MUTED)
ax.add_patch(FancyBboxPatch((620, 250), 640, 640, boxstyle="round,pad=0,rounding_size=24",
                            fc="#121a22", ec=TEAL, lw=3))
ax.text(940, 290, "Elasticsearch (Serverless)", fontsize=28, weight="bold", color=TEAL, ha="center", va="center")
box(ax, 660, 340, 560, 150, "inspections\nsemantic_text\n(Mistral embeddings in Elastic)", TEAL, 21)
box(ax, 660, 520, 560, 150, "complaints_311\ngeo_point + created_date", TEAL, 21)
box(ax, 660, 700, 560, 150, "forecasts\nevery prediction\nqueried with ES|QL", TEAL, 21)
box(ax, 1420, 330, 410, 300, "Mistral Large 4\nfunction-calling agent\n\n-> grade + score\n+ reasoning", ORANGE, 24)
ax.text(1625, 700, "tools", fontsize=24, color=ORANGE, ha="center", weight="bold")
for i, t in enumerate(["get_inspection_history", "nearby_complaints (geo_distance)",
                       "neighborhood_baseline (aggs)", "similar_violation_restaurants"]):
    ax.text(1625, 750 + i * 42, t, fontsize=19, family="DejaVu Sans Mono", ha="center", color=FG)
arrow(ax, (470, 440), (620, 440))
arrow(ax, (1420, 480), (1260, 480), ORANGE)
arrow(ax, (1260, 600), (1420, 600), TEAL)
ax.text(1340, 455, "query", fontsize=18, color=ORANGE, ha="center")
ax.text(1340, 640, "evidence", fontsize=18, color=TEAL, ha="center")
ax.add_patch(FancyBboxPatch((90, 950), 1740, 80, boxstyle="round,pad=0,rounding_size=14", fc="#2a1a12", ec=ORANGE, lw=2))
ax.text(960, 990, "Leakage guard:  inspection_date < as_of   |   created_date < as_of   - the answer is never visible",
        fontsize=24, ha="center", va="center")
save(fig, "02.png")

# 3-4. Agent trace from demo_run.txt
lines = open(os.path.join(ROOT, "demo_run.txt")).read().splitlines()


def terminal(name, title, body, footer=None):
    fig, ax = canvas()
    header(ax, title)
    ax.add_patch(FancyBboxPatch((90, 240), 1740, 780, boxstyle="round,pad=0,rounding_size=16", fc="#0a0d10", ec="#2d3a48", lw=2))
    for i, c in enumerate([RED, YELLOW, GREEN]):
        ax.add_patch(plt.Circle((130 + i * 36, 275), 10, color=c))
    y = 340
    for text, color in body:
        for w in textwrap.wrap(text, 92, subsequent_indent="     ") or [""]:
            ax.text(130, y, w, fontsize=21, family="DejaVu Sans Mono", color=color, va="center"); y += 38
    if footer:
        ax.add_patch(FancyBboxPatch((1290, 930), 500, 70, boxstyle="round,pad=0,rounding_size=12", fc="#3a1416", ec=RED, lw=3))
        ax.text(1540, 965, footer, fontsize=30, weight="bold", color=FG, ha="center", va="center")
    save(fig, name)


tool_body = [("$ python agent.py 50033403 2026-06-15", GREEN), ("", FG)]
for l in lines[1:lines.index(next(x for x in lines if x.startswith("=>")))]:
    if l.startswith("->"): tool_body.append((l, ORANGE))
    elif l.strip(): tool_body.append((l.rstrip(), FG))
terminal("03.png", "Agent run: Guiz Hou Miao Jia Noodles, Flushing", tool_body)

verdict = next(l for l in lines if l.startswith("=>"))
reason = lines[lines.index(verdict) + 1].strip()
excerpt = reason.split(" Adjustments:")[0]
adj = "Adjustments: " + reason.split(" Adjustments:")[1].split(";")[0]
terminal("04.png", "Verdict, using only evidence before 2026-06-15",
         [(verdict, ORANGE), ("", FG), (excerpt, FG), ("", FG), (adj, FG), ("", FG),
          ("Total ~ 25 + 9 = ~30, in the C band (28+).", YELLOW)],
         footer="Actual: C (score 55)")

# 5. Backtest v1 vs v2 (numbers from backtest_v1.log / backtest_v2.log)
def metrics(log):
    t = open(os.path.join(ROOT, log)).read()
    acc = [float(x) for x in re.search(r"Accuracy\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%", t).groups()]
    rec = [float(x) for x in re.search(r"C-grade recall\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%", t).groups()]
    return acc, rec
a1, r1 = metrics("backtest_v1.log"); a2, r2 = metrics("backtest_v2.log")
series = [("Agent v1", r1[0], a1[0], "#6e7b88"), ("Agent v2 (held-out)", r2[0], a2[0], ORANGE),
          ("Baseline: same grade as last time", r2[1], a2[1], BLUE), ("Baseline: last score -> band", r2[2], a2[2], TEAL)]
fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
fig.text(0.047, 0.91, "Backtest: v1 lost, v2 catches the C restaurants", fontsize=46, weight="bold")
fig.text(0.048, 0.855, "30 stratified inspections per run (10 A / 10 B / 10 C). v2 re-scored on a fresh sample.  Baselines shown on the v2 sample.",
         fontsize=21, color=MUTED)
ax = fig.add_axes([0.07, 0.12, 0.88, 0.66], facecolor=BG)
w = 0.2
for i, (name, rec, acc, col) in enumerate(series):
    xs = [0 + (i - 1.5) * w, 1 + (i - 1.5) * w]
    bars = ax.bar(xs, [rec, acc], w * 0.92, color=col, label=name)
    for b, v in zip(bars, [rec, acc]):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center", fontsize=24, weight="bold")
ax.set_xticks([0, 1], ["C-grade recall", "Overall accuracy"], fontsize=28)
ax.set_ylim(0, 105); ax.set_yticks([]); [s.set_visible(False) for s in ax.spines.values()]
ax.legend(fontsize=20, frameon=False, loc="upper right", ncol=2, labelcolor=FG)
fig.savefig(os.path.join(OUT, "05.png"), facecolor=BG); plt.close(fig)

# 6. Per-grade accuracy from live forecasts index (ES|QL), fallback results_v2.csv
src = "Elastic `forecasts` index via ES|QL"
try:
    es = Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=30)
    r = es.esql.query(query="FROM forecasts | STATS n = COUNT(*), agent = AVG(CASE(correct, 1.0, 0.0)), "
                            "base = AVG(CASE(baseline_correct, 1.0, 0.0)) BY actual_grade | SORT actual_grade | LIMIT 10").body
    cols = [c["name"] for c in r["columns"]]
    pg = pd.DataFrame(r["values"], columns=cols)
except Exception as e:
    print("ES|QL failed, using CSV:", repr(e)[:200]); src = "results_v2.csv"
    df = pd.read_csv(os.path.join(ROOT, "results_v2.csv"))
    pg = df.groupby("actual_grade").agg(n=("camis", "size"), agent=("correct", "mean"), base=("baseline_correct", "mean")).reset_index()
print(pg)
fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
fig.text(0.047, 0.91, "Accuracy by actual grade", fontsize=46, weight="bold")
fig.text(0.048, 0.855, f"Source: live {src}  -  the trade-off: v2 flags risk, but over-flags A restaurants",
         fontsize=21, color=MUTED)
ax = fig.add_axes([0.07, 0.12, 0.88, 0.66], facecolor=BG)
x = range(len(pg))
for off, colname, col, lab in [(-0.18, "agent", ORANGE, "Agent v2"), (0.18, "base", BLUE, "Baseline: same grade as last time")]:
    bars = ax.bar([i + off for i in x], pg[colname] * 100, 0.34, color=col, label=lab)
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5, f"{b.get_height():.0f}%", ha="center", fontsize=24, weight="bold")
ax.set_xticks(list(x), [f"Actual {g}  (n={n})" for g, n in zip(pg["actual_grade"], pg["n"])], fontsize=28)
ax.set_ylim(0, 125); ax.set_yticks([]); [s.set_visible(False) for s in ax.spines.values()]
ax.legend(fontsize=22, frameon=False, loc="upper center", ncol=2, labelcolor=FG)
fig.savefig(os.path.join(OUT, "06.png"), facecolor=BG); plt.close(fig)

# 7. 311 complaints map from complaints_311
try:
    r = es.esql.query(query="FROM complaints_311 | EVAL lon = ST_X(location), lat = ST_Y(location) "
                            "| KEEP lon, lat, complaint_type | LIMIT 10000").body
    pts = pd.DataFrame(r["values"], columns=[c["name"] for c in r["columns"]]); msrc = "Elastic complaints_311 (geo_point), 10k sample"
except Exception as e:
    print("map ES|QL failed, using local data:", repr(e)[:200])
    raw = json.load(open(os.path.join(ROOT, "data", "complaints_311.json")))
    pts = pd.DataFrame([{"lon": float(d["longitude"]), "lat": float(d["latitude"]), "complaint_type": d["complaint_type"]}
                        for d in raw if d.get("latitude")]).sample(20000, random_state=0, replace=False)
    msrc = "311 complaints (local copy of the ingested data), 20k sample"
pts = pts.dropna(); pts = pts[(pts.lat > 40.45) & (pts.lat < 40.95) & (pts.lon > -74.3) & (pts.lon < -73.68)]
fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
fig.text(0.047, 0.91, "Elastic geo data: 311 complaints across NYC", fontsize=46, weight="bold")
fig.text(0.048, 0.855, f"{msrc}  -  the agent queries these with geo_distance + date range", fontsize=21, color=MUTED)
ax = fig.add_axes([0.3, 0.02, 0.6, 0.82], facecolor=BG)
palette = [RED, YELLOW, TEAL, BLUE, ORANGE, "#b083f0"]
for (t, g), c in zip(pts.groupby("complaint_type"), palette):
    ax.scatter(g.lon, g.lat, s=14, color=c, alpha=0.5, label=f"{t} ({len(g):,})", linewidths=0)
ax.set_aspect(1 / 0.758); ax.axis("off")
leg = fig.legend(fontsize=26, frameon=False, loc="center left", bbox_to_anchor=(0.05, 0.5), markerscale=3, labelcolor=FG)
fig.savefig(os.path.join(OUT, "07.png"), facecolor=BG); plt.close(fig)

# 8. Agent Builder chat (from converse.json, captured by converse.py)
cv = os.path.join(HERE, "converse.json")
if os.path.exists(cv):
    d = json.load(open(cv))
    msg = d["response"]["message"]
    tools = [s.get("tool_id") for s in d.get("steps", []) if s.get("type") == "tool_call"]
    fig, ax = canvas()
    header(ax, "Kibana Agent Builder: \"NYC Inspection Analyst\"", "Mistral Medium  +  5 ES|QL tools  +  semantic search  -  real response via converse API")
    q = "Which restaurants did the forecaster correctly flag as C?"
    ax.add_patch(FancyBboxPatch((760, 240), 1070, 80, boxstyle="round,pad=0,rounding_size=16", fc="#1f3a5f", ec=BLUE, lw=2))
    ax.text(1810, 280, q, fontsize=24, ha="right", va="center")
    ax.text(110, 365, "tool call:  " + ", ".join(tools), fontsize=20, color=TEAL, family="DejaVu Sans Mono", va="center")
    ax.add_patch(FancyBboxPatch((90, 400), 1740, 620, boxstyle="round,pad=0,rounding_size=16", fc="#18212b", ec="#2d3a48", lw=2))
    intro, *rest = msg.split("\n\n", 1)
    ax.text(120, 450, intro.replace("**", "").replace("`", ""), fontsize=21, va="center")
    rows = [r for r in (rest[0] if rest else "").splitlines() if r.startswith("|") and "---" not in r]
    y = 520
    for k, row in enumerate(rows):
        cells = [c.strip().replace("**", "") for c in row.strip("|").split("|")]
        for cx, c in zip([120, 960, 1260, 1520], cells):
            ax.text(cx, y, c, fontsize=21, va="center", weight="bold" if k == 0 else "normal", color=MUTED if k == 0 else FG)
        y += 52
    save(fig, "08.png")

# 9. Takeaways
fig, ax = canvas()
header(ax, "Takeaways")
items = [(GREEN, "Strong early warning: catches 9/10 C restaurants (baselines: 1/10 and 8/10)"),
         (YELLOW, "Not a better all-round predictor yet: 43% vs 47% accuracy (over-flags A's)"),
         (TEAL, "The backtest made it better: v1's 0% C recall exposed a bad assumption"),
         (BLUE, "Next: bigger backtest, calibrate A's, match 311 complaints to the restaurant")]
for i, (c, t) in enumerate(items):
    ax.add_patch(plt.Circle((120, 300 + i * 130), 14, color=c))
    ax.text(160, 300 + i * 130, t, fontsize=27, va="center")
ax.text(960, 900, "github.com/Ttheegela/inspection-forecaster", fontsize=40, color=ORANGE, ha="center", weight="bold")
ax.text(960, 975, "Elastic  x  Mistral NYC Hack Night", fontsize=24, color=MUTED, ha="center")
save(fig, "09.png")
print("done", sorted(os.listdir(OUT)))
