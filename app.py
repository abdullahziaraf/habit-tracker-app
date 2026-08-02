"""
Habit Tracker — a single-file, local-first Streamlit app.

Run it with:
    streamlit run habit_tracker.py

Tracks any number of habits independently (each with its own streak),
plus a derived "perfect day" streak for days where every habit was done.
No external APIs, no accounts, no cost — data is stored in a local SQLite
file (habit_tracker.db) created next to this script the first time you run it.
"""

import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Database layer (SQLite, local file, no server needed)
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "habit_tracker.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#4C9A6A',
            created_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            habit_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            PRIMARY KEY (habit_id, log_date),
            FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def add_habit(name: str, color: str = "#4C9A6A"):
    name = name.strip()
    if not name:
        return False, "Habit name cannot be empty."
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO habits (name, color, created_at) VALUES (?, ?, ?)",
            (name, color, datetime.now().isoformat()),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "A habit with that name already exists."
    finally:
        conn.close()


def delete_habit(habit_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()


def archive_habit(habit_id: int, archived: bool = True):
    conn = get_connection()
    conn.execute("UPDATE habits SET archived = ? WHERE id = ?", (int(archived), habit_id))
    conn.commit()
    conn.close()


def get_habits(include_archived: bool = False):
    conn = get_connection()
    if include_archived:
        rows = conn.execute("SELECT * FROM habits ORDER BY created_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM habits WHERE archived = 0 ORDER BY created_at"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_log(habit_id: int, log_date: str) -> bool:
    """Toggle a habit's completion for a given ISO date string. Returns new state."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT 1 FROM logs WHERE habit_id = ? AND log_date = ?", (habit_id, log_date)
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM logs WHERE habit_id = ? AND log_date = ?", (habit_id, log_date)
        )
        conn.commit()
        conn.close()
        return False
    conn.execute(
        "INSERT INTO logs (habit_id, log_date) VALUES (?, ?)", (habit_id, log_date)
    )
    conn.commit()
    conn.close()
    return True


def is_done(habit_id: int, log_date: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM logs WHERE habit_id = ? AND log_date = ?", (habit_id, log_date)
    ).fetchone()
    conn.close()
    return row is not None


def get_logs_for_habit(habit_id: int, since: str = None):
    conn = get_connection()
    if since:
        rows = conn.execute(
            "SELECT log_date FROM logs WHERE habit_id = ? AND log_date >= ? ORDER BY log_date",
            (habit_id, since),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT log_date FROM logs WHERE habit_id = ? ORDER BY log_date", (habit_id,)
        ).fetchall()
    conn.close()
    return [r["log_date"] for r in rows]


def get_all_logs(since: str = None):
    conn = get_connection()
    if since:
        rows = conn.execute(
            "SELECT habit_id, log_date FROM logs WHERE log_date >= ? ORDER BY log_date",
            (since,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT habit_id, log_date FROM logs ORDER BY log_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_streaks(done_dates: set):
    """
    Given a set of `date` objects a habit was completed on, return
    (current_streak, longest_streak).

    Current streak: walk backward from today. If today isn't done yet,
    start counting from yesterday instead. Stop at the first gap.
    Longest streak: scan the full history for the longest unbroken run.
    """
    if not done_dates:
        return 0, 0

    today = date.today()
    current = 0
    cursor = today
    if cursor not in done_dates:
        cursor -= timedelta(days=1)
    while cursor in done_dates:
        current += 1
        cursor -= timedelta(days=1)

    sorted_dates = sorted(done_dates)
    longest = 1
    run = 1
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)

    return current, longest


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Habit Tracker", page_icon="🔥", layout="wide")
init_db()

TODAY = date.today()
TODAY_STR = TODAY.isoformat()

PALETTE = ["#4C9A6A", "#3B7DD8", "#D8823B", "#B5539A", "#43A6A6", "#C24C4C", "#8C7AE6"]


def habit_color(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


st.markdown(
    """
    <style>
    .habit-card {
        background-color: rgba(127, 127, 127, 0.08);
        border-radius: 12px;
        padding: 16px 18px;
        margin-bottom: 10px;
    }
    .habit-name {
        font-size: 1.05rem;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .habit-streak {
        font-size: 0.9rem;
        opacity: 0.8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def compute_perfect_streak(habits: list) -> int:
    """Days in a row (up to today) where every current habit was completed."""
    if not habits:
        return 0
    all_logs = get_all_logs()
    if not all_logs:
        return 0
    df = pd.DataFrame(all_logs)
    df["log_date"] = df["log_date"].apply(date.fromisoformat)
    habit_ids = {h["id"] for h in habits}
    earliest = min(datetime.fromisoformat(h["created_at"]).date() for h in habits)

    def all_done_on(d: date) -> bool:
        done_ids = set(df.loc[df["log_date"] == d, "habit_id"])
        return habit_ids.issubset(done_ids)

    cursor = TODAY
    if not all_done_on(cursor):
        cursor -= timedelta(days=1)

    streak = 0
    while cursor >= earliest and all_done_on(cursor):
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def build_heatmap(habit: dict, weeks: int = 18):
    """GitHub-style contribution heatmap for a single habit."""
    end = TODAY
    start = end - timedelta(weeks=weeks - 1)
    start -= timedelta(days=start.weekday())  # snap back to a Monday

    done_dates = {
        date.fromisoformat(d)
        for d in get_logs_for_habit(habit["id"], since=start.isoformat())
    }

    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    records = []
    for d in pd.date_range(start, end, freq="D").date:
        records.append(
            {
                "week": (d - start).days // 7,
                "weekday_label": weekday_labels[d.weekday()],
                "done": 1 if d in done_dates else 0,
                "label": d.strftime("%b %d, %Y"),
            }
        )
    df = pd.DataFrame(records)

    return (
        alt.Chart(df)
        .mark_rect(cornerRadius=3)
        .encode(
            x=alt.X("week:O", axis=None),
            y=alt.Y("weekday_label:N", sort=weekday_labels, title=None),
            color=alt.Color(
                "done:Q",
                scale=alt.Scale(domain=[0, 1], range=["#3a3a3a", habit["color"]]),
                legend=None,
            ),
            tooltip=[alt.Tooltip("label:N", title="Date"), alt.Tooltip("done:Q", title="Done")],
        )
        .properties(height=180)
    )


def build_comparison_chart(habits: list, days_back: int = 30):
    """Bar chart: completion % per habit over the last N days."""
    since = (TODAY - timedelta(days=days_back - 1)).isoformat()
    rows = []
    for h in habits:
        logs = get_logs_for_habit(h["id"], since=since)
        created = datetime.fromisoformat(h["created_at"]).date()
        active_days = max(min(days_back, (TODAY - created).days + 1), 1)
        pct = round(len(logs) / active_days * 100, 1)
        rows.append({"habit": h["name"], "completion": pct, "color": h["color"]})
    df = pd.DataFrame(rows)

    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("habit:N", title=None, sort="-y"),
            y=alt.Y("completion:Q", title="Completion %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color(
                "habit:N",
                legend=None,
                scale=alt.Scale(domain=df["habit"].tolist(), range=df["color"].tolist()),
            ),
            tooltip=["habit", "completion"],
        )
        .properties(height=320)
    )


def build_period_stats(habits: list) -> pd.DataFrame:
    """Weekly and monthly completion percentage per habit."""
    week_start = TODAY - timedelta(days=TODAY.weekday())
    month_start = TODAY.replace(day=1)

    rows = []
    for h in habits:
        week_logs = get_logs_for_habit(h["id"], since=week_start.isoformat())
        month_logs = get_logs_for_habit(h["id"], since=month_start.isoformat())
        days_this_week = (TODAY - week_start).days + 1
        days_this_month = (TODAY - month_start).days + 1
        rows.append(
            {
                "Habit": h["name"],
                "This week": f"{len(week_logs)}/{days_this_week} "
                f"({round(len(week_logs) / days_this_week * 100)}%)",
                "This month": f"{len(month_logs)}/{days_this_month} "
                f"({round(len(month_logs) / days_this_month * 100)}%)",
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

habits = get_habits()

header_col, metric_col = st.columns([3, 1])
with header_col:
    st.title("🔥 Habit Tracker")
    st.caption(TODAY.strftime("%A, %B %d, %Y"))
with metric_col:
    st.metric(
        "Perfect day streak",
        f"{compute_perfect_streak(habits)} 🏆",
        help="Consecutive days where every habit was completed",
    )

# Simple in-app reminder banner. Only appears while the app is open in a
# browser tab — not a push/email/OS notification.
if habits:
    pending = [h for h in habits if not is_done(h["id"], TODAY_STR)]
    if pending:
        st.info(f"⏰ Still pending today: **{', '.join(h['name'] for h in pending)}**")
    else:
        st.success("✅ All habits complete for today. Nice work!")

st.divider()

tab_today, tab_insights, tab_manage = st.tabs(["📅 Today", "📊 Insights", "⚙️ Manage"])

# ---------------------------------------------------------------------------
# Today tab
# ---------------------------------------------------------------------------

with tab_today:
    if not habits:
        st.warning("No habits yet — add one from the **Manage** tab to get started.")
    else:
        cols = st.columns(3)
        for i, h in enumerate(habits):
            done_dates = {date.fromisoformat(d) for d in get_logs_for_habit(h["id"])}
            current, longest = compute_streaks(done_dates)
            is_today_done = TODAY in done_dates
            color = h["color"] or habit_color(i)

            with cols[i % 3]:
                st.markdown(
                    f"""
                    <div class="habit-card" style="border-left: 6px solid {color};">
                        <div class="habit-name">{h['name']}</div>
                        <div class="habit-streak">🔥 {current} day{'s' if current != 1 else ''}
                        &nbsp;·&nbsp; best {longest}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                label = "✅ Done today" if is_today_done else "Mark done"
                if st.button(
                    label,
                    key=f"toggle_{h['id']}",
                    width="stretch",
                    type="primary" if is_today_done else "secondary",
                ):
                    toggle_log(h["id"], TODAY_STR)
                    st.rerun()

# ---------------------------------------------------------------------------
# Insights tab
# ---------------------------------------------------------------------------

with tab_insights:
    if not habits:
        st.info("Add some habits first to see insights here.")
    else:
        st.subheader("Consistency heatmap")
        selected_name = st.selectbox("Choose a habit", [h["name"] for h in habits])
        selected_habit = next(h for h in habits if h["name"] == selected_name)
        st.altair_chart(build_heatmap(selected_habit), width="stretch")

        st.subheader("Completion rate comparison (last 30 days)")
        st.altair_chart(build_comparison_chart(habits), width="stretch")

        st.subheader("Weekly & monthly completion")
        st.dataframe(build_period_stats(habits), width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Manage tab
# ---------------------------------------------------------------------------

with tab_manage:
    st.subheader("Add a new habit")
    with st.form("add_habit_form", clear_on_submit=True):
        name = st.text_input("Habit name", placeholder="e.g. Drink 2L water")
        color = st.color_picker("Color", value=habit_color(len(habits)))
        submitted = st.form_submit_button("Add habit")
        if submitted:
            ok, err = add_habit(name, color)
            if ok:
                st.success(f"Added '{name.strip()}'")
                st.rerun()
            else:
                st.error(err)

    st.divider()
    st.subheader("Your habits")
    if not habits:
        st.caption("Nothing here yet.")
    for h in habits:
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.write(f"**{h['name']}**")
        if c2.button("Archive", key=f"archive_{h['id']}"):
            archive_habit(h["id"], True)
            st.rerun()
        if c3.button("Delete", key=f"delete_{h['id']}"):
            delete_habit(h["id"])
            st.rerun()

    st.divider()
    st.subheader("Export data")
    all_logs = get_all_logs()
    if all_logs:
        export_df = pd.DataFrame(all_logs)
        habit_map = {h["id"]: h["name"] for h in get_habits(include_archived=True)}
        export_df["habit"] = export_df["habit_id"].map(habit_map)
        export_df = export_df[["habit", "log_date"]].rename(columns={"log_date": "date"})
        st.download_button(
            "Download CSV",
            export_df.to_csv(index=False).encode("utf-8"),
            "habit_log.csv",
            "text/csv",
        )
    else:
        st.caption("No data yet to export.")
