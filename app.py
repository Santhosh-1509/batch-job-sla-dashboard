import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from alerts import generate_alerts, LEVELS
from anomaly_detection import detect_runtime_anomalies
from data_loader import (
    HISTORY_FILE_VARIABLE,
    load_job_config,
    load_dependencies,
)
from dependency_engine import build_graph, find_connected_jobs
from risk_score import calculate_risk_scores, WEIGHTS
from root_cause import build_run_issues, trace_root_cause
from simulator import OUTPUT_FILE, SCENARIOS, run_simulation
from sla_analysis import analyse_sla

st.set_page_config(
    page_title="Batch Job Monitoring Dashboard",
    page_icon="📊",
    layout="wide",
)

# ---------- Colours and icons ----------
GREEN = "#2e9e5b"
AMBER = "#e0a800"
ORANGE = "#e8590c"
RED = "#c92a2a"
BLUE = "#1c7ed6"
GREY = "#868e96"
PURPLE = "#7048e8"

RISK_COLOURS = {"LOW": GREEN, "MEDIUM": AMBER, "HIGH": ORANGE, "CRITICAL": RED}
LEVEL_ICONS = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}

STATUS_COLOURS = {
    "COMPLETED": GREEN,
    "FAILED": RED,
    "RUNNING": BLUE,
    "QUEUED": GREY,
}

RUNTIME_COLOURS = {
    "WITHIN_LIMIT": GREEN,
    "MINOR_OVERRUN": AMBER,
    "MAJOR_OVERRUN": RED,
}

SLA_COLOURS = {
    "MET": GREEN,
    "APPROACHING": AMBER,
    "BREACHED": RED,
    "PENDING": GREY,
}

FACTOR_LABELS = {
    "failure_pts": "Failure history",
    "sla_pts": "SLA risk",
    "runtime_pts": "Runtime behaviour",
    "dependency_pts": "Dependency impact",
    "criticality_pts": "Criticality",
}

FACTOR_COLOURS = {
    "Failure history": RED,
    "SLA risk": ORANGE,
    "Runtime behaviour": AMBER,
    "Dependency impact": PURPLE,
    "Criticality": BLUE,
}

# Every status word that should be coloured inside tables.
CELL_COLOURS = {
    "LOW": GREEN,
    "MEDIUM": AMBER,
    "HIGH": ORANGE,
    "CRITICAL": RED,
    "COMPLETED": GREEN,
    "FAILED": RED,
    "RUNNING": BLUE,
    "QUEUED": GREY,
    "MET": GREEN,
    "APPROACHING": AMBER,
    "BREACHED": RED,
    "PENDING": GREY,
    "WITHIN_LIMIT": GREEN,
    "MINOR_OVERRUN": AMBER,
    "MAJOR_OVERRUN": RED,
    "NORMAL": GREEN,
    "UNUSUALLY_LONG": RED,
    "UNUSUALLY_SHORT": BLUE,
    "INSUFFICIENT_HISTORY": GREY,
    "INCREASING": ORANGE,
    "STABLE": GREEN,
    "DECREASING": BLUE,
    "NOT_ENOUGH_DATA": GREY,
    "SLA_BREACHED": RED,
    "MAJOR_RUNTIME_OVERRUN": RED,
    "SLA_APPROACHING": AMBER,
    "UNUSUAL_RUNTIME": AMBER,
    "HIGH_RISK_JOB": ORANGE,
    "CAUSE": RED,
    "PROBLEM": AMBER,
}

VIEWS = [
    "📊 Operations Overview",
    "🔎 Job Explorer",
    "⏱️ SLA Analytics",
    "🔗 Dependency Explorer",
    "🚨 Risk & Alerts",
]

# Data sources the person can choose in the sidebar.
SOURCES = {
    "📁 Original dataset": "original",
    "🟢 Simulated: normal": "normal",
    "🟡 Simulated: degraded": "degraded",
    "🔴 Simulated: bad day": "bad_day",
    "🔵 Simulated: live snapshot": "live",
}

CSS = """
<style>
.banner {background: linear-gradient(90deg, #1c7ed6, #7048e8); padding: 18px 24px; border-radius: 12px; margin-bottom: 18px;}
.banner h1 {margin: 0; font-size: 1.7rem; color: white;}
.banner p {margin: 4px 0 0 0; color: white; opacity: 0.9;}
.kpi {background: rgba(128,128,128,0.10); border-left: 6px solid #1c7ed6; border-radius: 10px; padding: 14px 16px; margin-bottom: 8px; min-height: 100px;}
.kpi .label {font-size: 0.85rem; opacity: 0.8;}
.kpi .value {font-size: 1.9rem; font-weight: 700;}
.badge {display: inline-block; padding: 4px 14px; border-radius: 999px; color: white; font-weight: 700;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- Helper functions ----------
def kpi_card(icon, label, value, colour):
    """Return the HTML for one coloured number card."""
    return (
        f'<div class="kpi" style="border-left-color:{colour}">'
        f'<div class="label">{icon} {label}</div>'
        f'<div class="value" style="color:{colour}">{value}</div>'
        f"</div>"
    )


def show_cards(cards):
    """Show a row of number cards."""
    for column, card in zip(st.columns(len(cards)), cards):
        column.markdown(kpi_card(*card), unsafe_allow_html=True)


def badge(text, colour):
    """Return the HTML for a small coloured badge."""
    return f'<span class="badge" style="background:{colour}">{text}</span>'


def colour_cell(value):
    """Colour a table cell when it holds a known status word."""
    if not isinstance(value, str):
        return ""
    colour = CELL_COLOURS.get(value.split(" ")[-1])
    if colour is None:
        return ""
    return f"background-color: {colour}; color: white; font-weight: 600"


def show_table(df):
    """Show a table with coloured status cells."""
    st.dataframe(df.style.map(colour_cell), hide_index=True)


def with_icon(level):
    """Turn 'HIGH' into the text '🟠 HIGH'."""
    return f"{LEVEL_ICONS.get(level, '')} {level}"


def tidy_figure(fig):
    """Apply the same spacing to every chart."""
    fig.update_layout(margin=dict(t=50, b=20, l=20, r=20))
    return fig


def download_button(df, label, file_name):
    """Offer a table as a CSV download."""
    st.download_button(
        label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
    )


def filter_by_text(df, text):
    """Keep the jobs that match every word typed in the search box.

    The words are looked for in the job ID, job name, criticality and
    risk level, so 'order critical' finds critical jobs with 'order'
    in the name.
    """
    words = text.lower().split()
    if not words:
        return df

    haystack = (
        df["job_id"].astype(str)
        + " "
        + df["job_name"].astype(str)
        + " "
        + df["criticality"].astype(str)
        + " "
        + df["risk_level"].astype(str)
    ).str.lower()

    keep = pd.Series(True, index=df.index)
    for word in words:
        keep &= haystack.str.contains(word, regex=False)
    return df[keep]


def open_in_explorer(job_name):
    """Jump to the Job Explorer view with the chosen job selected."""
    st.session_state["view"] = VIEWS[1]
    st.session_state["explorer_job"] = job_name


def prepare_source(source_key):
    """Point the analysis modules at the chosen data source.

    For the original dataset nothing is needed. For a simulated scenario
    the simulation is run (same seed = same data) and saved to a file that
    the other modules then read.
    """
    if source_key == "original":
        os.environ.pop(HISTORY_FILE_VARIABLE, None)
        return

    history, _ = run_simulation(source_key)
    history.to_csv(OUTPUT_FILE, index=False)
    os.environ[HISTORY_FILE_VARIABLE] = OUTPUT_FILE.name


@st.cache_data
def load_all(source_key):
    """Run all calculations once per data source and keep the results."""
    prepare_source(source_key)

    runs = detect_runtime_anomalies()
    sla = analyse_sla()[
        [
            "execution_id",
            "sla_status",
            "end_datetime",
            "sla_deadline_datetime",
        ]
    ]
    runs = runs.merge(sla, on="execution_id", how="left")
    runs["run_date"] = pd.to_datetime(runs["run_date"])

    # Minutes after the SLA deadline (negative = finished early).
    runs["sla_minutes_late"] = (
        runs["end_datetime"] - runs["sla_deadline_datetime"]
    ).dt.total_seconds() / 60

    scores = calculate_risk_scores()
    alerts = generate_alerts()
    jobs = load_job_config()

    return runs, scores, alerts, jobs


@st.cache_data
def load_dependency_data(source_key):
    """Load dependency lookups and the per-run problem list."""
    prepare_source(source_key)

    dependencies = load_dependencies()
    downstream_map, upstream_map = build_graph(dependencies)
    run_issues = build_run_issues()
    return dependencies, downstream_map, upstream_map, run_issues


# ---------- Operations Overview ----------
def show_job_search(runs, scores, alerts):
    """Search box that finds jobs and can open them in the Job Explorer."""
    st.subheader("🔍 Find a job")
    text = st.text_input(
        "Search by job name, job ID, criticality or risk level",
        placeholder="Examples: order   |   JOB013   |   critical   |   high",
        key="job_search",
    )

    if not text.strip():
        return

    latest = (
        runs.sort_values(["job_id", "run_date"])
        .groupby("job_id")
        .tail(1)[["job_id", "status", "sla_status"]]
        .rename(columns={"status": "latest_status", "sla_status": "latest_sla"})
    )
    alert_counts = (
        alerts.groupby("job_id").size().rename("active_alerts").reset_index()
        if not alerts.empty
        else pd.DataFrame(columns=["job_id", "active_alerts"])
    )

    table = (
        scores[["job_id", "job_name", "criticality", "risk_score", "risk_level"]]
        .merge(latest, on="job_id", how="left")
        .merge(alert_counts, on="job_id", how="left")
    )
    table["active_alerts"] = table["active_alerts"].fillna(0).astype(int)
    table = filter_by_text(table, text).sort_values(
        "risk_score", ascending=False
    )

    if table.empty:
        st.info("No jobs match your search.")
        return

    st.caption(f"{len(table)} job(s) found, highest risk first.")
    display = table.copy()
    display["risk_level"] = display["risk_level"].map(with_icon)
    show_table(display)

    pick_col, button_col = st.columns([3, 1])
    pick = pick_col.selectbox(
        "Open one of these jobs",
        table["job_name"].tolist(),
        key="search_pick",
    )
    button_col.write("")
    button_col.button(
        "🔎 Open in Job Explorer",
        on_click=open_in_explorer,
        args=(pick,),
    )


def show_overview(runs, scores, alerts):
    st.header("📊 Operations Overview")

    show_job_search(runs, scores, alerts)

    latest = runs.sort_values(["job_id", "run_date"]).groupby("job_id").tail(1)

    failed = int((latest["status"] == "FAILED").sum())
    waiting = int(latest["status"].isin(["QUEUED", "RUNNING"]).sum())
    breached = int((latest["sla_status"] == "BREACHED").sum())
    risky = int(scores["risk_level"].isin(["HIGH", "CRITICAL"]).sum())

    show_cards(
        [
            ("📦", "Jobs monitored", len(scores), BLUE),
            ("❌", "Failed jobs", failed, RED),
            ("⏳", "Queued / running", waiting, GREY),
            ("⏰", "SLA breached", breached, ORANGE),
            ("🔥", "High-risk jobs", risky, PURPLE),
            ("🚨", "Active alerts", len(alerts), AMBER),
        ]
    )

    st.caption(
        "Failed, queued / running and SLA breached are counted from each "
        "job's latest run."
    )

    left, middle, right = st.columns(3)

    # Chart 1: executions per day, split by status.
    by_day = (
        runs.assign(day=runs["run_date"].dt.strftime("%Y-%m-%d"))
        .groupby(["day", "status"])
        .size()
        .reset_index(name="runs")
    )
    fig_days = px.bar(
        by_day,
        x="day",
        y="runs",
        color="status",
        color_discrete_map=STATUS_COLOURS,
        title="📅 Executions by day",
    )
    left.plotly_chart(tidy_figure(fig_days))

    # Chart 2: jobs at each risk level (donut).
    risk_counts = (
        scores["risk_level"]
        .value_counts()
        .reindex(LEVELS, fill_value=0)
        .reset_index()
    )
    risk_counts.columns = ["risk_level", "jobs"]
    fig_risk = px.pie(
        risk_counts,
        names="risk_level",
        values="jobs",
        hole=0.5,
        color="risk_level",
        color_discrete_map=RISK_COLOURS,
        title="🎯 Jobs by risk level",
    )
    middle.plotly_chart(tidy_figure(fig_risk))

    # Chart 3: alerts by severity.
    if alerts.empty:
        right.success("No active alerts.")
    else:
        severity_counts = (
            alerts["severity"]
            .value_counts()
            .reindex(LEVELS, fill_value=0)
            .reset_index()
        )
        severity_counts.columns = ["severity", "alerts"]
        fig_alerts = px.bar(
            severity_counts,
            x="severity",
            y="alerts",
            color="severity",
            color_discrete_map=RISK_COLOURS,
            text="alerts",
            title="🚨 Alerts by severity",
        )
        right.plotly_chart(tidy_figure(fig_alerts))

    st.subheader("🚨 Top alerts")
    if alerts.empty:
        st.success("No active alerts.")
    else:
        top_alerts = alerts.head(10).copy()
        top_alerts["severity"] = top_alerts["severity"].map(with_icon)
        show_table(top_alerts)

    st.subheader("🔥 Highest-risk jobs")
    top_jobs = scores[
        [
            "job_id",
            "job_name",
            "criticality",
            "risk_score",
            "risk_level",
            "downstream_jobs",
            "trend",
        ]
    ].head(10).copy()
    top_jobs["risk_level"] = top_jobs["risk_level"].map(with_icon)
    show_table(top_jobs)


# ---------- Job Explorer ----------
def show_job_explorer(runs, scores, jobs, alerts):
    st.header("🔎 Job Explorer")

    ordered = scores.sort_values("risk_score", ascending=False)
    choice = st.selectbox(
        "Select a job (you can type to search)",
        ordered["job_name"].tolist(),
        key="explorer_job",
    )

    score = scores[scores["job_name"] == choice].iloc[0]
    job = jobs[jobs["job_id"] == score["job_id"]].iloc[0]
    job_runs = runs[runs["job_id"] == score["job_id"]].sort_values("run_date")

    level_colour = RISK_COLOURS[score["risk_level"]]
    st.markdown(
        f"### {score['job_name']} &nbsp; "
        f"{badge(score['risk_level'] + ' RISK', level_colour)}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Job ID: {score['job_id']}  |  Schedule: {job['schedule']}  |  "
        f"Downstream jobs: {score['downstream_jobs']}  |  "
        f"Runtime trend: {score['trend']}"
    )

    show_cards(
        [
            ("🎯", "Risk score", score["risk_score"], level_colour),
            ("⭐", "Criticality", job["criticality"],
             RISK_COLOURS.get(str(job["criticality"]).upper(), BLUE)),
            ("⏰", "SLA deadline", job["sla_deadline"], BLUE),
            ("⏳", "Max runtime (min)", int(job["max_runtime_minutes"]), PURPLE),
        ]
    )

    left, right = st.columns(2)

    # Chart 1: runtime of every finished run against the limit.
    finished = job_runs[job_runs["runtime_minutes"].notna()].copy()
    finished["day"] = finished["run_date"].dt.strftime("%Y-%m-%d")
    fig_runtime = px.scatter(
        finished,
        x="day",
        y="runtime_minutes",
        color="runtime_status",
        color_discrete_map=RUNTIME_COLOURS,
        title="⏱️ Runtime per run (minutes)",
    )
    fig_runtime.add_scatter(
        x=finished["day"],
        y=finished["runtime_minutes"],
        mode="lines",
        line=dict(color="#adb5bd"),
        showlegend=False,
    )
    # Draw the connecting line first so the dots sit on top of it.
    fig_runtime.data = (fig_runtime.data[-1],) + fig_runtime.data[:-1]
    fig_runtime.update_traces(
        marker=dict(size=13), selector=dict(mode="markers")
    )
    fig_runtime.add_hline(
        y=float(job["max_runtime_minutes"]),
        line_dash="dash",
        line_color=RED,
        annotation_text="Max runtime",
    )
    left.plotly_chart(tidy_figure(fig_runtime))

    # Chart 2: how many points each factor added to the risk score.
    breakdown = pd.DataFrame(
        {
            "factor": list(FACTOR_LABELS.values()),
            "points": [score[column] for column in FACTOR_LABELS],
        }
    )
    fig_breakdown = px.bar(
        breakdown,
        x="factor",
        y="points",
        color="factor",
        color_discrete_map=FACTOR_COLOURS,
        text="points",
        title="🧮 Risk score breakdown (points)",
    )
    fig_breakdown.update_layout(showlegend=False)
    right.plotly_chart(tidy_figure(fig_breakdown))

    st.caption(
        "Maximum points per factor: "
        + ", ".join(f"{name} {value}" for name, value in WEIGHTS.items())
    )

    st.subheader("🚨 Alerts for this job")
    job_alerts = alerts[alerts["job_id"] == score["job_id"]].copy()
    if job_alerts.empty:
        st.success("No active alerts for this job.")
    else:
        job_alerts["severity"] = job_alerts["severity"].map(with_icon)
        show_table(job_alerts)

    st.subheader("📜 Execution history")
    table = job_runs.copy()
    table["run_date"] = table["run_date"].dt.strftime("%Y-%m-%d")
    show_table(
        table[
            [
                "execution_id",
                "run_date",
                "start_time",
                "end_time",
                "status",
                "runtime_minutes",
                "runtime_status",
                "sla_status",
                "anomaly_status",
            ]
        ]
    )


# ---------- SLA Analytics ----------
def show_sla_analytics(runs):
    st.header("⏱️ SLA Analytics")

    finished = runs[
        runs["sla_status"].isin(["MET", "APPROACHING", "BREACHED"])
    ].copy()
    finished["day"] = finished["run_date"].dt.strftime("%Y-%m-%d")
    breaches = finished[finished["sla_status"] == "BREACHED"].copy()

    total = len(finished)
    breached = len(breaches)
    approaching = int((finished["sla_status"] == "APPROACHING").sum())
    compliance = (total - breached) / total * 100 if total else 0.0

    if compliance >= 95:
        compliance_colour = GREEN
    elif compliance >= 90:
        compliance_colour = AMBER
    else:
        compliance_colour = RED

    show_cards(
        [
            ("✅", "SLA compliance", f"{compliance:.1f}%", compliance_colour),
            ("⛔", "Breached runs", breached, RED),
            ("⚠️", "Close to deadline", approaching, AMBER),
            ("📦", "Jobs with a breach", breaches["job_id"].nunique(), ORANGE),
        ]
    )
    st.caption(
        "Compliance = finished runs that did not breach their SLA deadline. "
        "'Close to deadline' means finished within 15 minutes of it."
    )

    left, right = st.columns(2)

    # Chart 1: SLA status per day.
    by_day = (
        runs.assign(day=runs["run_date"].dt.strftime("%Y-%m-%d"))
        .groupby(["day", "sla_status"])
        .size()
        .reset_index(name="runs")
    )
    fig_days = px.bar(
        by_day,
        x="day",
        y="runs",
        color="sla_status",
        color_discrete_map=SLA_COLOURS,
        category_orders={
            "sla_status": ["MET", "APPROACHING", "BREACHED", "PENDING"]
        },
        title="📅 SLA status by day",
    )
    left.plotly_chart(tidy_figure(fig_days))

    # Chart 2: compliance by job criticality.
    by_criticality = (
        finished.assign(ok=finished["sla_status"] != "BREACHED")
        .groupby("criticality")["ok"]
        .mean()
        .mul(100)
        .round(1)
        .reindex(LEVELS)
        .dropna()
        .reset_index()
    )
    by_criticality.columns = ["criticality", "compliance"]
    fig_criticality = px.bar(
        by_criticality,
        x="criticality",
        y="compliance",
        color="criticality",
        color_discrete_map=RISK_COLOURS,
        text="compliance",
        title="🎯 SLA compliance % by job criticality",
    )
    fig_criticality.update_layout(yaxis_range=[0, 100], showlegend=False)
    right.plotly_chart(tidy_figure(fig_criticality))

    if breaches.empty:
        st.success("No SLA breaches found.")
        return

    left2, right2 = st.columns(2)

    # Chart 3: minutes after the deadline for every job that breached.
    breaching_jobs = breaches["job_name"].unique()
    drift = finished[finished["job_name"].isin(breaching_jobs)].sort_values(
        "run_date"
    )
    fig_drift = px.line(
        drift,
        x="day",
        y="sla_minutes_late",
        color="job_name",
        markers=True,
        title="📈 Minutes after SLA deadline (above 0 = breached)",
    )
    fig_drift.add_hline(
        y=0,
        line_dash="dash",
        line_color=RED,
        annotation_text="SLA deadline",
    )
    left2.plotly_chart(tidy_figure(fig_drift))

    # Chart 4: number of breaches per job.
    by_job = (
        breaches.groupby("job_name")
        .size()
        .reset_index(name="breaches")
        .sort_values("breaches")
    )
    fig_by_job = px.bar(
        by_job,
        x="breaches",
        y="job_name",
        orientation="h",
        color_discrete_sequence=[RED],
        text="breaches",
        title="⛔ Breaches per job",
    )
    right2.plotly_chart(tidy_figure(fig_by_job))

    st.subheader("⛔ Breach details (latest and worst first)")
    table = breaches.copy()
    table["run_date"] = table["run_date"].dt.strftime("%Y-%m-%d")
    table["finished_at"] = table["end_datetime"].dt.strftime("%Y-%m-%d %H:%M")
    table["deadline"] = table["sla_deadline_datetime"].dt.strftime("%H:%M")
    table["minutes_late"] = table["sla_minutes_late"].round(0).astype(int)
    table = table.sort_values("minutes_late", ascending=False)[
        [
            "execution_id",
            "job_name",
            "run_date",
            "finished_at",
            "deadline",
            "minutes_late",
            "criticality",
        ]
    ]
    show_table(table)
    download_button(table, "⬇️ Download breach details (CSV)", "sla_breaches.csv")


# ---------- Dependency Explorer ----------
def connected_table(pairs, score_lookup):
    """Turn (job_id, level) pairs into a table."""
    rows = []
    for job_id, level in pairs:
        rows.append(
            {
                "level": level,
                "job_id": job_id,
                "job_name": score_lookup.loc[job_id, "job_name"],
                "criticality": score_lookup.loc[job_id, "criticality"],
                "risk_level": with_icon(score_lookup.loc[job_id, "risk_level"]),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["level", "job_id", "job_name", "criticality", "risk_level"]
        )
    return pd.DataFrame(rows).sort_values(["level", "job_name"])


def build_network_figure(
    job_id, upstream_list, downstream_list, dependencies, score_lookup
):
    """Draw the selected job with its upstream and downstream jobs."""

    # Column 0 = selected job, negative = upstream, positive = downstream.
    columns = {0: [job_id]}
    for jid, level in upstream_list:
        columns.setdefault(-level, []).append(jid)
    for jid, level in downstream_list:
        columns.setdefault(level, []).append(jid)

    positions = {}
    for x, members in columns.items():
        for i, jid in enumerate(members):
            if jid not in positions:
                positions[jid] = (x, (len(members) - 1) / 2 - i)

    fig = go.Figure()

    # Arrows for every dependency between the jobs shown.
    for _, row in dependencies.iterrows():
        up = str(row["upstream_job_id"]).strip()
        down = str(row["downstream_job_id"]).strip()
        if up in positions and down in positions:
            x0, y0 = positions[up]
            x1, y1 = positions[down]
            fig.add_annotation(
                x=x1,
                y=y1,
                ax=x0,
                ay=y0,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                text="",
                arrowhead=2,
                arrowwidth=1.5,
                arrowcolor="#adb5bd",
                standoff=14,
                startstandoff=14,
            )

    # One group of dots per risk level, so the legend explains the colours.
    for level in LEVELS:
        members = [
            jid
            for jid in positions
            if score_lookup.loc[jid, "risk_level"] == level
        ]
        if not members:
            continue
        fig.add_trace(
            go.Scatter(
                x=[positions[j][0] for j in members],
                y=[positions[j][1] for j in members],
                mode="markers+text",
                name=f"{level} risk",
                text=[score_lookup.loc[j, "job_name"] for j in members],
                textposition="top center",
                textfont=dict(size=11),
                hovertext=[
                    f"{score_lookup.loc[j, 'job_name']}<br>"
                    f"Risk score {score_lookup.loc[j, 'risk_score']} "
                    f"({level})<br>"
                    f"Criticality {score_lookup.loc[j, 'criticality']}"
                    for j in members
                ],
                hoverinfo="text",
                marker=dict(
                    size=24,
                    color=RISK_COLOURS[level],
                    line=dict(
                        width=[4 if j == job_id else 1 for j in members],
                        color="#212529",
                    ),
                ),
            )
        )

    xs = sorted(columns.keys())
    labels = []
    for x in xs:
        if x == 0:
            labels.append("Selected job")
        elif x < 0:
            labels.append(f"Upstream L{-x}")
        else:
            labels.append(f"Downstream L{x}")

    tallest = max(len(members) for members in columns.values())
    fig.update_layout(
        title="🔗 Dependency map (left to right: upstream → selected → downstream)",
        height=max(420, 90 * tallest + 160),
        xaxis=dict(
            tickmode="array",
            tickvals=xs,
            ticktext=labels,
            showgrid=False,
            zeroline=False,
            range=[min(xs) - 0.6, max(xs) + 0.6],
        ),
        yaxis=dict(visible=False),
        margin=dict(t=50, b=20, l=20, r=20),
    )
    return fig


def show_dependency_explorer(scores, source_key):
    st.header("🔗 Dependency Explorer")

    dependencies, downstream_map, upstream_map, run_issues = (
        load_dependency_data(source_key)
    )
    score_lookup = scores.set_index("job_id")

    ordered = scores.sort_values("risk_score", ascending=False)
    choice = st.selectbox(
        "Select a job (you can type to search)",
        ordered["job_name"].tolist(),
        key="dependency_job",
    )
    job_id = scores.loc[scores["job_name"] == choice, "job_id"].iloc[0]

    upstream_list = find_connected_jobs(job_id, upstream_map)
    downstream_list = find_connected_jobs(job_id, downstream_map)

    critical_downstream = sum(
        1
        for jid, _ in downstream_list
        if score_lookup.loc[jid, "criticality"] == "CRITICAL"
    )
    level = score_lookup.loc[job_id, "risk_level"]

    show_cards(
        [
            ("⬆️", "Upstream jobs", len(upstream_list), BLUE),
            ("⬇️", "Downstream jobs affected", len(downstream_list), ORANGE),
            ("⭐", "Critical jobs downstream", critical_downstream, RED),
            ("🎯", "Risk level", level, RISK_COLOURS[level]),
        ]
    )

    if not upstream_list and not downstream_list:
        st.info("This job has no upstream or downstream dependencies.")
    else:
        fig = build_network_figure(
            job_id, upstream_list, downstream_list, dependencies, score_lookup
        )
        st.plotly_chart(fig)

    left, right = st.columns(2)
    with left:
        st.subheader("⬆️ Upstream (this job waits for)")
        if upstream_list:
            show_table(connected_table(upstream_list, score_lookup))
        else:
            st.caption("No upstream jobs.")
    with right:
        st.subheader("⬇️ Downstream (hurt if this job fails)")
        if downstream_list:
            show_table(connected_table(downstream_list, score_lookup))
        else:
            st.caption("No downstream jobs.")

    # ----- Root-cause tracing -----
    st.subheader("🔍 Root-cause tracing")
    st.caption(
        "Pick a date to see which upstream jobs also had a problem that day "
        "(failed, SLA breached or major runtime overrun)."
    )

    dates = sorted(run_issues["run_date"].unique())
    own_days = run_issues[
        (run_issues["job_id"] == job_id) & (run_issues["issues"] != "")
    ]["run_date"].tolist()
    default_index = dates.index(own_days[0]) if own_days else len(dates) - 1

    chosen_date = st.selectbox(
        "Date",
        dates,
        index=default_index,
        key=f"root_cause_date_{source_key}_{job_id}",
    )

    own = run_issues[
        (run_issues["job_id"] == job_id)
        & (run_issues["run_date"] == chosen_date)
    ]
    own_issues = own["issues"].iloc[0] if not own.empty else ""

    if own_issues:
        st.warning(f"{choice} on {chosen_date}: {own_issues}")
    else:
        st.success(f"{choice} had no problems on {chosen_date}.")

    trace = trace_root_cause(job_id, chosen_date, run_issues, upstream_map)
    if trace:
        trace_table = pd.DataFrame(trace)
        trace_table["role"] = trace_table["is_root"].map(
            {True: "⭐ POSSIBLE ROOT CAUSE", False: "Upstream PROBLEM"}
        )
        trace_table = trace_table.sort_values(
            ["is_root", "levels_up"], ascending=[False, True]
        )[["role", "job_id", "job_name", "levels_up", "issues"]]
        show_table(trace_table)
    elif own_issues:
        st.info(
            "No upstream job had a problem on this date, so the problem "
            "appears to start at this job."
        )

    st.caption(
        "These are possible causes only. They are based on problems on the "
        "same date; the data does not show timing between jobs."
    )

    # ----- Biggest downstream impact -----
    st.subheader("💥 Jobs with the biggest downstream impact")
    impact = scores.sort_values("downstream_jobs", ascending=False).head(10)
    fig_impact = px.bar(
        impact.sort_values("downstream_jobs"),
        x="downstream_jobs",
        y="job_name",
        orientation="h",
        color="risk_level",
        color_discrete_map=RISK_COLOURS,
        text="downstream_jobs",
        title="Downstream jobs affected if this job fails",
    )
    st.plotly_chart(tidy_figure(fig_impact))


# ---------- Risk & Alerts ----------
def show_risk_alerts(scores, alerts):
    st.header("🚨 Risk & Alerts")

    if alerts.empty:
        alert_cards = [("🚨", "Active alerts", 0, GREEN)]
    else:
        alert_cards = [
            ("🚨", "Active alerts", len(alerts), AMBER),
            ("🔴", "Critical alerts", int((alerts["severity"] == "CRITICAL").sum()), RED),
            ("🟠", "High alerts", int((alerts["severity"] == "HIGH").sum()), ORANGE),
            ("📦", "Jobs with alerts", alerts["job_id"].nunique(), BLUE),
        ]
    show_cards(alert_cards)

    # ----- Alerts -----
    st.subheader("🚨 Alerts")
    if alerts.empty:
        st.success("No active alerts.")
    else:
        severity_options = list(reversed(LEVELS))
        type_options = sorted(alerts["alert_type"].unique())

        f1, f2, f3 = st.columns(3)
        severities = f1.multiselect(
            "Severity", severity_options, default=severity_options
        )
        types = f2.multiselect("Alert type", type_options, default=type_options)
        search = f3.text_input("Search job name")

        filtered = alerts[
            alerts["severity"].isin(severities)
            & alerts["alert_type"].isin(types)
        ]
        if search:
            filtered = filtered[
                filtered["job_name"].str.contains(search, case=False, na=False)
            ]

        st.caption(f"Showing {len(filtered)} of {len(alerts)} alerts")
        if filtered.empty:
            st.info("No alerts match the filters.")
        else:
            display = filtered.copy()
            display["severity"] = display["severity"].map(with_icon)
            show_table(display)
            download_button(filtered, "⬇️ Download alerts (CSV)", "alerts.csv")

    # ----- Risk scores -----
    st.subheader("🧮 How the top risk scores were built")
    top = scores.head(10)
    long_form = top.melt(
        id_vars=["job_name"],
        value_vars=list(FACTOR_LABELS.keys()),
        var_name="factor",
        value_name="points",
    )
    long_form["factor"] = long_form["factor"].map(FACTOR_LABELS)
    fig_stack = px.bar(
        long_form,
        x="points",
        y="job_name",
        color="factor",
        orientation="h",
        color_discrete_map=FACTOR_COLOURS,
        category_orders={"job_name": top["job_name"].tolist()},
        title="Risk score points by factor (top 10 jobs)",
    )
    fig_stack.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(tidy_figure(fig_stack))

    st.subheader("🔥 All job risk scores")
    r1, r2 = st.columns(2)
    levels_chosen = r1.multiselect(
        "Risk level",
        list(reversed(LEVELS)),
        default=list(reversed(LEVELS)),
        key="risk_level_filter",
    )
    risk_search = r2.text_input(
        "Search job name, job ID or criticality",
        key="risk_table_search",
    )

    matching = filter_by_text(
        scores[scores["risk_level"].isin(levels_chosen)], risk_search
    )
    table = matching[
        [
            "job_id",
            "job_name",
            "criticality",
            "risk_score",
            "risk_level",
            "failure_pts",
            "sla_pts",
            "runtime_pts",
            "dependency_pts",
            "criticality_pts",
            "failed_runs",
            "sla_breaches",
            "major_overruns",
            "trend",
            "downstream_jobs",
        ]
    ]
    st.caption(f"Showing {len(table)} of {len(scores)} jobs")
    if table.empty:
        st.info("No jobs match the filter.")
    else:
        display = table.copy()
        display["risk_level"] = display["risk_level"].map(with_icon)
        show_table(display)
        download_button(table, "⬇️ Download risk scores (CSV)", "risk_scores.csv")


# ---------- Main ----------
def main():
    st.markdown(
        '<div class="banner">'
        "<h1>📦 Batch Job Monitoring and SLA Risk Analysis</h1>"
        "<p>Synthetic data for learning and demonstration only.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.sidebar.title("🧭 Navigation")
    view = st.sidebar.radio("View", VIEWS, key="view")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**🗂️ Data source**")
    source_label = st.sidebar.selectbox(
        "Choose the data to analyse",
        list(SOURCES.keys()),
        label_visibility="collapsed",
    )
    source_key = SOURCES[source_label]

    if source_key == "original":
        st.sidebar.caption("The original 30-job dataset.")
    else:
        st.sidebar.caption(SCENARIOS[source_key]["description"])

    with st.spinner("Calculating..."):
        runs, scores, alerts, jobs = load_all(source_key)

    first_day = runs["run_date"].min().strftime("%d %b %Y")
    last_day = runs["run_date"].max().strftime("%d %b %Y")
    st.sidebar.caption(f"Runs from {first_day} to {last_day}")

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Colour guide**")
    st.sidebar.markdown(
        "🟢 Low / OK  \n"
        "🟡 Medium / Approaching  \n"
        "🟠 High  \n"
        "🔴 Critical / Failed"
    )

    if view == VIEWS[0]:
        show_overview(runs, scores, alerts)
    elif view == VIEWS[1]:
        show_job_explorer(runs, scores, jobs, alerts)
    elif view == VIEWS[2]:
        show_sla_analytics(runs)
    elif view == VIEWS[3]:
        show_dependency_explorer(scores, source_key)
    else:
        show_risk_alerts(scores, alerts)


main()