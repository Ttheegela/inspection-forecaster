"""Inspection Forecaster: public Streamlit demo over a static snapshot (app_data/)."""
import ast
import io
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import segno
import streamlit as st

st.set_page_config(page_title="Inspection Forecaster", page_icon="🍽️", layout="wide")

REPO = "https://github.com/Ttheegela/inspection-forecaster"
DATA = Path(__file__).parent / "app_data"
VIDEO = "https://youtu.be/irhme66ttB8"
GRADE_COLORS = {"A": [37, 99, 235], "B": [234, 179, 8], "C": [220, 38, 38]}
OTHER_COLOR = [148, 163, 184]
MAP_STYLE = pdk.map_styles.CARTO_LIGHT
MAX_POINTS = 20_000


@st.cache_data
def load_inspections():
    d = pd.read_csv(DATA / "inspections.csv.gz", dtype={"camis": str, "zipcode": str})
    d["inspection_date"] = pd.to_datetime(d["inspection_date"])
    d["violations"] = d["violations"].fillna("")
    return d


@st.cache_data
def load_complaints():
    c = pd.read_csv(DATA / "complaints_311.csv.gz")
    c["created_date"] = pd.to_datetime(c["created_date"])
    return c


@st.cache_data
def load_results(version):
    r = pd.read_csv(DATA / f"results_{version}.csv", dtype={"camis": str})
    r["ok"] = r["predicted_grade"].notna()  # v1 had 2 failed agent runs
    r["score_baseline_correct"] = r["score_baseline_grade"] == r["actual_grade"]
    return r


def metrics(r):
    """Accuracy and C recall for agent and both baselines, over rows the agent answered."""
    r = r[r["ok"]]
    c = r[r["actual_grade"] == "C"]
    rows = []
    for name, col in [("Agent", "correct"), ("Last grade", "baseline_correct"),
                      ("Last score → band", "score_baseline_correct")]:
        rows.append({"model": name, "accuracy": r[col].mean(), "c_recall": c[col].mean()})
    return pd.DataFrame(rows)


def haversine_m(lat, lon, lat0, lon0):
    lat, lon, lat0, lon0 = map(np.radians, (lat, lon, lat0, lon0))
    a = np.sin((lat - lat0) / 2) ** 2 + np.cos(lat) * np.cos(lat0) * np.sin((lon - lon0) / 2) ** 2
    return 2 * 6_371_000 * np.arcsin(np.sqrt(a))


def parse_list(s):
    try:
        return ast.literal_eval(s) if isinstance(s, str) else []
    except (ValueError, SyntaxError):
        return [s]


@st.cache_data
def qr_png(url):
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=8, border=2)
    return buf.getvalue()


def qr_pair(where):
    a, b = where.columns(2)
    a.image(qr_png(VIDEO), caption="Demo video", width="stretch")
    b.image(qr_png(REPO), caption="GitHub repo", width="stretch")


def grade_color(g):
    return GRADE_COLORS.get(g, OTHER_COLOR)


def results_section():
    st.markdown(
        "An agent predicts a NYC restaurant's **next health-inspection grade** (A/B/C) using only evidence "
        "dated *before* the inspection: its own history, 311 rodent / food-poisoning complaints nearby, the "
        "zip code's baseline, and restaurants with semantically similar violations (Elastic `semantic_text` "
        "+ Mistral embeddings). A backtest scores it against what actually happened and two naive baselines."
    )
    m1, m2 = metrics(r1).set_index("model"), metrics(r2).set_index("model")
    a, b, c, d = st.columns(4)
    a.metric("C-grade recall (agent v2)", f"{m2.loc['Agent', 'c_recall']:.0%}",
             f"{m2.loc['Agent', 'c_recall'] - m2.loc['Last grade', 'c_recall']:+.0%} vs last grade")
    b.metric("C recall: last grade / last score", f"{m2.loc['Last grade', 'c_recall']:.0%} / "
             f"{m2.loc['Last score → band', 'c_recall']:.0%}")
    c.metric("Accuracy (agent v2)", f"{m2.loc['Agent', 'accuracy']:.0%}",
             f"{m2.loc['Agent', 'accuracy'] - m2.loc['Last grade', 'accuracy']:+.0%} vs last grade")
    d.metric("Accuracy: last grade / last score", f"{m2.loc['Last grade', 'accuracy']:.0%} / "
             f"{m2.loc['Last score → band', 'accuracy']:.0%}")

    both = pd.concat([metrics(r1).assign(run="v1 (30 inspections)"), metrics(r2).assign(run="v2 (held-out 30)")])
    long = both.melt(["model", "run"], ["accuracy", "c_recall"], "metric", "value")
    long["metric"] = long["metric"].map({"accuracy": "Accuracy", "c_recall": "C-grade recall"})
    chart = alt.Chart(long).mark_bar().encode(
        x=alt.X("model:N", title=None, sort=["Agent", "Last grade", "Last score → band"]),
        y=alt.Y("value:Q", axis=alt.Axis(format="%"), title=None, scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("model:N", legend=None),
        column=alt.Column("metric:N", title=None),
        row=alt.Row("run:N", title=None),
        tooltip=["run", "model", "metric", alt.Tooltip("value:Q", format=".0%")],
    ).properties(width=260, height=160)
    st.altair_chart(chart)
    st.markdown(
        "**What changed v1 → v2.** v1 predicted B for every actual C: it assumed restaurants improve after a bad "
        "inspection. v2 anchors on the last score and assumes no improvement, and was re-scored on a fresh sample. "
        "v2 is a strong C-risk detector but over-flags A restaurants.\n\n"
        "**Caveats.** 30 inspections per run, stratified 10 A / 10 B / 10 C, so accuracy is not the real-world "
        "grade mix (mostly A). v1 metrics exclude 2 failed agent runs."
    )


insp, comp = load_inspections(), load_complaints()
r1, r2 = load_results("v1"), load_results("v2")

st.title("🍽️ Inspection Forecaster")
st.caption("Snapshot data (NYC Open Data, Oct 2025 – Oct 2026), not live. The forecasting agent "
           "(Mistral Large + Elasticsearch) runs locally with API keys; this app shows its saved backtest "
           f"and the same evidence it reads. Code: [{REPO.split('github.com/')[1]}]({REPO})")

page = st.sidebar.radio("Page", ["1-minute pitch", "Walkthrough", "Backtest explorer", "Restaurant lookup", "City explorer"])
st.sidebar.divider()
st.sidebar.markdown("**Scan to watch or fork**")
qr_pair(st.sidebar)

STEPS = ["1 · The question", "2 · The data", "3 · The agent", "4 · Did it work?", "5 · Explore & links"]

# ---------------------------------------------------------------- 1-minute pitch
if page == "1-minute pitch":
    st.markdown(
        "<h2 style='margin-bottom:0'>Can AI predict a NYC restaurant's health grade "
        "<span style='color:#FA520F'>before the inspector arrives?</span></h2>"
        "<p style='color:#666;margin-top:4px'>Mistral Large 4 agent · Elasticsearch evidence dated before the "
        "inspection · backtested against what really happened</p>", unsafe_allow_html=True)
    m2 = metrics(r2).set_index("model")
    k = st.columns(4)
    k[0].metric("C restaurants caught", f"{round(m2.loc['Agent', 'c_recall'] * 10)} / 10",
                f"vs {round(m2.loc['Last grade', 'c_recall'] * 10)}/10 'same as last time'")
    k[1].metric("v1 → v2", "0 → 9 of 10", "backtest exposed a bad assumption")
    k[2].metric("Inspections in Elastic", f"{len(insp):,}", f"{insp['camis'].nunique():,} restaurants", delta_color="off")
    k[3].metric("311 complaints (geo)", f"{len(comp):,}", "rodent · food poisoning", delta_color="off")

    left, right = st.columns([3, 2], gap="medium")
    with left:
        heat = comp.dropna(subset=["lat"])[["lat", "lon"]]
        cs = insp[insp["grade"] == "C"].dropna(subset=["lat"]).drop_duplicates("camis")
        cs = cs.assign(label=cs["dba"] + " · C (" + cs["score"].astype("Int64").astype(str) + ")")
        st.pydeck_chart(pdk.Deck(
            layers=[
                pdk.Layer("HeatmapLayer", heat, get_position="[lon, lat]", radius_pixels=25, intensity=1,
                          threshold=0.05, opacity=0.55,
                          color_range=[[255, 237, 213], [254, 186, 116], [251, 146, 60], [250, 82, 15], [194, 49, 4]]),
                pdk.Layer("ScatterplotLayer", cs[["lat", "lon", "label"]], get_position="[lon, lat]",
                          get_fill_color=[17, 24, 39, 200], get_radius=45, radius_min_pixels=2, pickable=True),
            ],
            initial_view_state=pdk.ViewState(latitude=40.71, longitude=-73.93, zoom=9.6, pitch=0),
            map_style=MAP_STYLE, tooltip={"text": "{label}"}), height=430)
        st.caption("Heat: 311 rodent / food-poisoning complaints · dark dots: restaurants graded C")
    with right:
        st.markdown("**Live example: Guiz Hou Miao Jia Noodles, Flushing**")
        g = insp[insp["camis"] == "50033403"].sort_values("inspection_date")
        a, b = st.columns(2)
        a.metric("Agent forecast", "C", "score ~30", delta_color="off")
        b.metric("Actual (2026-06-15)", "C", "score 55", delta_color="off")
        st.markdown(
            "- Last score **25**: both baselines said A or B\n"
            "- **Food-poisoning** 311 complaint 100 m away, 8 days before\n"
            "- Uncorrected temperature + pest violations\n"
            "- Zip 11354: 27% of inspections are C")
        both = pd.concat([metrics(r1).assign(run="v1"), metrics(r2).assign(run="v2 (held-out)")])
        both = both[(both["model"] == "Agent") | (both["run"] == "v2 (held-out)")]
        both["label"] = both["model"].where(both["model"] != "Agent", "Agent " + both["run"])
        st.altair_chart(alt.Chart(both, title="C-grade recall").mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("label:N", title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False), sort=["Agent v1", "Agent v2 (held-out)", "Last grade", "Last score → band"]),
            x=alt.X("c_recall:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.condition(alt.datum.label == "Agent v2 (held-out)", alt.value("#FA520F"), alt.value("#C9C4BD")),
            tooltip=["label", alt.Tooltip("c_recall:Q", format=".0%")]).properties(height=190), width="stretch")
        st.caption(f"Honest trade-off: accuracy {m2.loc['Agent', 'accuracy']:.0%} vs "
                   f"{m2.loc['Last score → band', 'accuracy']:.0%} for the best baseline (over-flags A's).")
    q = st.columns([1, 1, 1, 3])
    q[0].image(qr_png(VIDEO), caption="Demo video", width=130)
    q[1].image(qr_png(REPO), caption="GitHub", width=130)
    q[3].markdown("<br>**Elastic** geo + time + semantic retrieval · **Mistral** reasoning, embeddings & voice · "
                  "**a backtest** to prove it.", unsafe_allow_html=True)

# ---------------------------------------------------------------- Walkthrough
elif page == "Walkthrough":
    step = st.session_state.setdefault("step", 0)
    st.progress((step + 1) / len(STEPS), text=STEPS[step])

    if step == 0:
        st.header("Can AI predict a restaurant's health grade before the inspector arrives?")
        st.markdown(
            f"NYC grades every restaurant it inspects **A** (0–13 points), **B** (14–27) or **C** (28+); "
            f"this snapshot covers {insp['camis'].nunique():,} restaurants. "
            "Inspectors are limited, so knowing *which* restaurants are likely to fail matters.\n\n"
            "We built a **Mistral Large 4 agent** that forecasts the next grade using only evidence that existed "
            "**before** the inspection, stored and searched in **Elasticsearch**, then checked it against what "
            "actually happened.")
        st.info("Built in ~2 hours at the Elastic × Mistral NYC Hack Night, Oct 7 2026.")
    elif step == 1:
        st.header("The data")
        a, b, c = st.columns(3)
        a.metric("Inspections", f"{len(insp):,}", f"{insp['camis'].nunique():,} restaurants", delta_color="off")
        b.metric("311 complaints", f"{len(comp):,}", "rodent · food poisoning · food establishment", delta_color="off")
        c.metric("Backtested forecasts", f"{len(r1) + len(r2)}", "two runs of 30", delta_color="off")
        st.markdown(
            "- **DOHMH restaurant inspections** (Oct 2025 – Oct 2026): one record per inspection with score, grade "
            "and violations. Violation text is a `semantic_text` field embedded with **Mistral embeddings** "
            "inside Elastic.\n"
            "- **311 complaints** (Aug 2024 – Oct 2026) with locations (`geo_point`), so the agent can ask "
            "\"what did neighbors report within 75 m in the 90 days before?\"")
        pts = comp.dropna(subset=["lat"]).sample(min(15_000, len(comp)), random_state=0)
        st.pydeck_chart(pdk.Deck(
            layers=[pdk.Layer("ScatterplotLayer", pts[["lat", "lon"]], get_position="[lon, lat]",
                              get_fill_color=[220, 38, 38, 90], get_radius=35, radius_min_pixels=1)],
            initial_view_state=pdk.ViewState(latitude=40.71, longitude=-73.95, zoom=9.5), map_style=MAP_STYLE))
        st.caption("311 complaints across NYC (sample of 15,000).")
    elif step == 2:
        st.header("How the agent works")
        left, right = st.columns([1, 1])
        left.markdown(
            "Mistral Large 4 decides which **Elasticsearch tools** to call:\n"
            "1. `get_inspection_history`: the restaurant's past scores and violations\n"
            "2. `nearby_complaints`: 311 complaints within a radius (`geo_distance` + date range)\n"
            "3. `neighborhood_baseline`: zip code grade mix (aggregations)\n"
            "4. `similar_violation_restaurants`: semantic search for look-alike histories\n\n"
            "**Leakage guard:** every tool is hard-wired to `date < inspection date`. "
            "The model can't see the answer.")
        right.markdown("**Example: Guiz Hou Miao Jia Noodles, Flushing, 2026-06-15**")
        right.code(
            "-> get_inspection_history()\n   1 prior inspection, score 25 (B band)\n"
            "-> nearby_complaints(radius_m=75, days=180)\n   2 Food Poisoning, 2 Food Establishment\n"
            "   (one food-poisoning complaint 8 days before)\n"
            "-> neighborhood_baseline()\n   zip 11354: avg 21.1, 27% of inspections C\n"
            "-> similar_violation_restaurants(...)\n\n"
            "=> Forecast: C (score ~30)\n   Actual:   C (score 55)", language=None)
        right.caption("Both naive baselines said A or B. Try it yourself in **Restaurant lookup**.")
    elif step == 3:
        st.header("Did it work?")
        results_section()
    else:
        st.header("Explore it yourself")
        st.markdown(
            "- **Backtest explorer**: every forecast with the agent's reasoning, vs what inspectors found\n"
            "- **Restaurant lookup**: any restaurant's history + 311 complaints around it (same as the agent's tool)\n"
            "- **City explorer**: grades and complaints by borough, cuisine and date\n\n"
            "Use the sidebar to switch pages.")
        st.subheader("Watch the demo · get the code")
        qr_pair(st.container(border=False))
        st.markdown(f"[{VIDEO}]({VIDEO}) · [{REPO}]({REPO})")

    st.divider()
    back, _, nxt = st.columns([1, 4, 1])
    if back.button("← Back", disabled=step == 0, width="stretch"):
        st.session_state.step -= 1
        st.rerun()
    if nxt.button("Next →", disabled=step == len(STEPS) - 1, width="stretch", type="primary"):
        st.session_state.step += 1
        st.rerun()

# ---------------------------------------------------------------- Backtest explorer
elif page == "Backtest explorer":
    version = st.radio("Run", ["v2", "v1"], horizontal=True)
    r = (r2 if version == "v2" else r1)[lambda x: x["ok"]].copy()
    f1, f2 = st.columns(2)
    grades = f1.multiselect("Actual grade", ["A", "B", "C"], ["A", "B", "C"])
    outcome = f2.radio("Outcome", ["All", "Correct", "Incorrect"], horizontal=True)
    view = r[r["actual_grade"].isin(grades)]
    if outcome != "All":
        view = view[view["correct"] == (outcome == "Correct")]

    cols = ["dba", "as_of", "actual_grade", "predicted_grade", "baseline_grade", "actual_score",
            "predicted_score", "confidence", "correct"]
    st.dataframe(view[cols], hide_index=True, width="stretch")

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Confusion matrix")
        cm = r.groupby(["actual_grade", "predicted_grade"]).size().reset_index(name="n")
        base = alt.Chart(cm).encode(x=alt.X("predicted_grade:N", title="Predicted"),
                                    y=alt.Y("actual_grade:N", title="Actual"))
        st.altair_chart(base.mark_rect().encode(color=alt.Color("n:Q", legend=None, scale=alt.Scale(scheme="blues")))
                        + base.mark_text(fontSize=16).encode(text="n:Q"), width="stretch")
    with right:
        st.subheader("Agent reasoning")
        if view.empty:
            st.info("No forecasts match these filters.")
        else:
            labels = (view["dba"] + " · " + view["as_of"] + " · actual " + view["actual_grade"]
                      + " / predicted " + view["predicted_grade"]).tolist()
            i = st.selectbox("Forecast", range(len(view)), format_func=lambda k: labels[k])
            row = view.iloc[i]
            k1, k2, k3 = st.columns(3)
            k1.metric("Predicted", f"{row['predicted_grade']} ({row['predicted_score']:.0f})")
            k2.metric("Actual", f"{row['actual_grade']} ({row['actual_score']:.0f})")
            k3.metric("Confidence", f"{row['confidence']:.0%}")
            st.write(row["reasoning"])
            actual = insp[(insp["camis"] == row["camis"]) &
                          (insp["inspection_date"] == pd.Timestamp(row["as_of"]))]["violations"]
            v1c, v2c = st.columns(2)
            v1c.markdown("**Likely violations (agent)**")
            v1c.markdown("\n".join(f"- {v}" for v in parse_list(row["likely_violations"])) or "_none_")
            v2c.markdown("**Actual violations cited**")
            cited = actual.iloc[0].split(" | ") if len(actual) and actual.iloc[0] else []
            v2c.markdown("\n".join(f"- {v}" for v in cited) or "_none in snapshot_")
            if "violation_hit" in row:
                st.caption(f"Violation overlap (judged in backtest): {'yes' if row['violation_hit'] else 'no'}")

# ---------------------------------------------------------------- Restaurant lookup
elif page == "Restaurant lookup":
    latest = insp.sort_values("inspection_date").groupby("camis").tail(1)
    q = st.text_input("Search restaurant name", "GUIZ HOU")
    hits = latest[latest["dba"].fillna("").str.contains(q.strip(), case=False, regex=False)] if q.strip() else latest
    hits = hits.head(200)
    if hits.empty:
        st.warning("No restaurants match.")
        st.stop()
    names = dict(zip(hits["camis"], hits["dba"] + " · " + hits["address"].fillna("") + " · " + hits["boro"].fillna("")))
    ids = list(names)
    default = ids.index("50033403") if "50033403" in ids else 0
    camis = st.selectbox(f"Restaurant ({len(ids)} matches)", ids, index=default, format_func=names.get)

    h = insp[insp["camis"] == camis].sort_values("inspection_date")
    top = h.iloc[-1]
    st.subheader(f"{top['dba']} — {top['cuisine']}, {top['address']}, {top['boro']} {top['zipcode']}")
    st.altair_chart(alt.Chart(h.dropna(subset=["score"])).mark_line(point=True).encode(
        x=alt.X("inspection_date:T", title=None), y=alt.Y("score:Q", title="Score (lower is better)"),
        tooltip=["inspection_date:T", "inspection_type", "score", "grade"],
    ) + alt.Chart(pd.DataFrame({"y": [14, 28]})).mark_rule(strokeDash=[4, 4], color="gray").encode(y="y:Q"),
        width="stretch")
    st.caption("Dashed lines: A ≤ 13, B 14–27, C ≥ 28.")
    st.dataframe(h[["inspection_date", "inspection_type", "score", "grade", "violations"]].iloc[::-1],
                 hide_index=True, width="stretch",
                 column_config={"inspection_date": st.column_config.DateColumn("date")})

    st.subheader("311 complaints nearby (the agent's `nearby_complaints` tool)")
    if pd.isna(top["lat"]):
        st.info("No coordinates for this restaurant.")
    else:
        c1, c2, c3 = st.columns(3)
        dates = h["inspection_date"].dt.date.tolist()[::-1]
        as_of = c1.selectbox("As of (inspection date)", dates)
        radius = c2.slider("Radius (m)", 50, 500, 75, 25)
        days = c3.slider("Days before", 30, 365, 90, 15)
        t0 = pd.Timestamp(as_of)
        win = comp[(comp["created_date"] < t0) & (comp["created_date"] >= t0 - pd.Timedelta(days=days))]
        win = win.assign(dist_m=haversine_m(win["lat"].values, win["lon"].values, top["lat"], top["lon"]))
        near = win[win["dist_m"] <= radius].sort_values("created_date", ascending=False)
        counts = near["complaint_type"].value_counts()
        st.write(f"**{len(near)}** complaints within {radius} m in the {days} days before {as_of}: "
                 + (", ".join(f"{k} {v}" for k, v in counts.items()) or "none"))
        pts = near.assign(color=[[220, 38, 38, 180]] * len(near), radius=8.0, label=near["complaint_type"]
                          + ": " + near["descriptor"].fillna("") + " (" + near["created_date"].dt.date.astype(str) + ")")
        me = pd.DataFrame([{"lat": top["lat"], "lon": top["lon"], "color": [37, 99, 235, 255], "radius": 14.0,
                            "label": top["dba"]}])
        circle = pdk.Layer("ScatterplotLayer", me, get_position="[lon, lat]", get_radius=radius,
                           get_fill_color=[37, 99, 235, 25], get_line_color=[37, 99, 235], stroked=True,
                           line_width_min_pixels=1)
        dots = pdk.Layer("ScatterplotLayer", pd.concat([pts, me])[["lat", "lon", "color", "radius", "label"]],
                         get_position="[lon, lat]", get_fill_color="color", get_radius="radius",
                         radius_min_pixels=4, pickable=True)
        zoom = 17 - np.log2(radius / 50)
        st.pydeck_chart(pdk.Deck(layers=[circle, dots], map_style=MAP_STYLE, tooltip={"text": "{label}"},
                                 initial_view_state=pdk.ViewState(latitude=top["lat"], longitude=top["lon"], zoom=zoom)))
        st.dataframe(near[["created_date", "complaint_type", "descriptor", "dist_m"]].round({"dist_m": 0}),
                     hide_index=True, width="stretch")

# ---------------------------------------------------------------- City explorer
else:
    mode = st.radio("Show", ["Inspections", "311 complaints"], horizontal=True)
    if mode == "Inspections":
        f1, f2, f3, f4 = st.columns(4)
        boros = f1.multiselect("Borough", sorted(insp["boro"].dropna().unique()))
        grades = f2.multiselect("Grade", ["A", "B", "C"], ["A", "B", "C"])
        cuisines = f3.multiselect("Cuisine", sorted(insp["cuisine"].dropna().unique()))
        lo, hi = insp["inspection_date"].min().date(), insp["inspection_date"].max().date()
        rng = f4.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
        d = insp[insp["grade"].isin(grades)]
        if boros:
            d = d[d["boro"].isin(boros)]
        if cuisines:
            d = d[d["cuisine"].isin(cuisines)]
        if len(rng) == 2:
            d = d[(d["inspection_date"] >= pd.Timestamp(rng[0])) & (d["inspection_date"] <= pd.Timestamp(rng[1]))]
        st.write(f"**{len(d):,}** graded inspections · avg score **{d['score'].mean():.1f}**")
        pts = d.dropna(subset=["lat"])
        if len(pts) > MAX_POINTS:
            pts = pts.sample(MAX_POINTS, random_state=0)
            st.caption(f"Map shows a random sample of {MAX_POINTS:,} points.")
        pts = pts.assign(color=pts["grade"].map(grade_color),
                         label=pts["dba"] + " · " + pts["grade"] + " (" + pts["score"].astype(str) + ")")
        st.pydeck_chart(pdk.Deck(
            layers=[pdk.Layer("ScatterplotLayer", pts[["lat", "lon", "color", "label"]], get_position="[lon, lat]",
                              get_fill_color="color", get_radius=40, radius_min_pixels=2, opacity=0.6, pickable=True)],
            initial_view_state=pdk.ViewState(latitude=40.71, longitude=-73.95, zoom=9.8),
            map_style=MAP_STYLE, tooltip={"text": "{label}"}))
        st.caption("● A blue · ● B yellow · ● C red")
        g1, g2 = st.columns(2)
        by_boro = d.groupby("boro", as_index=False)["score"].mean()
        g1.altair_chart(alt.Chart(by_boro, title="Avg score by borough").mark_bar().encode(
            x=alt.X("score:Q", title="Avg score"), y=alt.Y("boro:N", sort="-x", title=None)), width="stretch")
        by_cui = d.groupby("cuisine").agg(score=("score", "mean"), n=("score", "size")).reset_index()
        by_cui = by_cui[by_cui["n"] >= 20].nlargest(15, "score")
        g2.altair_chart(alt.Chart(by_cui, title="Worst cuisines by avg score (≥ 20 inspections)").mark_bar().encode(
            x=alt.X("score:Q", title="Avg score"), y=alt.Y("cuisine:N", sort="-x", title=None),
            tooltip=["cuisine", alt.Tooltip("score:Q", format=".1f"), "n"]), width="stretch")
    else:
        f1, f2, f3 = st.columns(3)
        types = f1.multiselect("Type", sorted(comp["complaint_type"].unique()), sorted(comp["complaint_type"].unique()))
        boros = f2.multiselect("Borough", sorted(comp["borough"].dropna().unique()))
        lo, hi = comp["created_date"].min().date(), comp["created_date"].max().date()
        rng = f3.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
        d = comp[comp["complaint_type"].isin(types)]
        if boros:
            d = d[d["borough"].isin(boros)]
        if len(rng) == 2:
            d = d[(d["created_date"] >= pd.Timestamp(rng[0])) & (d["created_date"] < pd.Timestamp(rng[1]) + pd.Timedelta(days=1))]
        st.write(f"**{len(d):,}** complaints")
        pts = d.sample(MAX_POINTS, random_state=0) if len(d) > MAX_POINTS else d
        if len(d) > MAX_POINTS:
            st.caption(f"Map shows a random sample of {MAX_POINTS:,} points.")
        palette = {"Rodent": [120, 72, 0], "Food Poisoning": [220, 38, 38], "Food Establishment": [124, 58, 237]}
        pts = pts.assign(color=pts["complaint_type"].map(lambda t: palette.get(t, OTHER_COLOR)),
                         label=pts["complaint_type"] + ": " + pts["descriptor"].fillna(""))
        st.pydeck_chart(pdk.Deck(
            layers=[pdk.Layer("ScatterplotLayer", pts[["lat", "lon", "color", "label"]], get_position="[lon, lat]",
                              get_fill_color="color", get_radius=40, radius_min_pixels=2, opacity=0.5, pickable=True)],
            initial_view_state=pdk.ViewState(latitude=40.71, longitude=-73.95, zoom=9.8),
            map_style=MAP_STYLE, tooltip={"text": "{label}"}))
        st.caption("● Rodent brown · ● Food Poisoning red · ● Food Establishment purple")
        weekly = (d.groupby([pd.Grouper(key="created_date", freq="W"), "complaint_type"]).size()
                  .reset_index(name="complaints"))
        st.altair_chart(alt.Chart(weekly, title="Complaints per week").mark_line().encode(
            x=alt.X("created_date:T", title=None), y="complaints:Q", color=alt.Color("complaint_type:N", title=None),
            tooltip=["created_date:T", "complaint_type", "complaints"]), width="stretch")
