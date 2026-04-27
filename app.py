import json
import re
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st

from modules import scoring
from modules.content_scout import ContentScout
from modules.storage import GitHubStorage
from modules.youtube_client import YouTubeClient

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Daily Learner",
    page_icon="📚",
    layout="centered",
)

# ── Password gate ──────────────────────────────────────────────────────────────

def _check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("📚 Daily Learner")
    pwd = st.text_input("Password", type="password", key="login_pwd")
    if st.button("Login", type="primary"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong password")
    return False

if not _check_password():
    st.stop()

# ── Service init (once per server process) ────────────────────────────────────

@st.cache_resource
def _init_services():
    storage = GitHubStorage(
        owner=st.secrets["GITHUB_REPO_OWNER"],
        repo=st.secrets["GITHUB_REPO_NAME"],
        branch=st.secrets.get("GITHUB_BRANCH", "main"),
        pat=st.secrets["GITHUB_PAT"],
    )
    scout = ContentScout(
        gemini_key=st.secrets["GEMINI_API_KEY"],
        groq_key=st.secrets.get("GROQ_API_KEY", ""),
    )
    yt = YouTubeClient(api_key=st.secrets["YOUTUBE_API_KEY"])
    return storage, scout, yt

storage, scout, yt_client = _init_services()

# ── Data helpers ──────────────────────────────────────────────────────────────

def get_user_data() -> dict:
    if "user_data" not in st.session_state:
        st.session_state.user_data = storage.load()
    return st.session_state.user_data

def save_user_data(data: dict):
    storage.save(data)
    st.session_state.user_data = data

def get_all_topics(user_data: dict) -> list:
    try:
        defaults = storage.load_topics()
    except Exception:
        defaults = []
    custom = user_data.get("custom_topics", [])
    return [t for t in defaults if t.get("active", True)] + custom

# ── Core action ───────────────────────────────────────────────────────────────

def _mark_learned(topic: dict, subject: str, video: dict | None, resources: list):
    data = get_user_data()
    record = {
        "id": str(uuid.uuid4()),
        "date": date.today().isoformat(),
        "topic_id": topic["id"],
        "topic_name": topic["name"],
        "subject": subject,
        "video_url": video["url"] if video else None,
        "video_title": video["title"] if video else None,
        "resources": resources or [],
        "completed": True,
        "completed_at": datetime.now().isoformat(),
    }
    data["sessions"].append(record)

    yr, mo = date.today().year, date.today().month
    key = f"{yr}-{mo:02d}"
    month_sessions = scoring.get_month_sessions(data["sessions"], yr, mo)
    n = len(month_sessions)
    data["monthly_stats"][key] = {"subjects_learned": n, "won": n >= 15}

    save_user_data(data)

# ── Learn Today page ───────────────────────────────────────────────────────────

def _step_topic_select(all_topics: list, sessions: list):
    st.title("What will you learn today?")
    today_str = date.today().strftime("%A, %B %d %Y")
    st.caption(today_str)
    st.markdown("---")

    yr, mo = date.today().year, date.today().month
    cols = st.columns(2)
    for i, topic in enumerate(all_topics):
        n = len(scoring.get_month_sessions(
            [s for s in sessions if s.get("topic_id") == topic["id"]], yr, mo
        ))
        label = f"**{topic['name']}**\n\n_{n} learned this month_"
        if cols[i % 2].button(label, key=f"topic_{topic['id']}", use_container_width=True):
            st.session_state.chosen_topic = topic
            st.session_state.learn_step = "subject_select"
            st.session_state.pop("subject_suggestions", None)
            st.rerun()


def _step_subject_select(sessions: list):
    topic = st.session_state.chosen_topic
    if st.button("← Back to topics"):
        st.session_state.learn_step = "topic_select"
        st.rerun()

    st.subheader(f"Choose a subject — {topic['name']}")
    st.caption("AI-generated suggestions, excluding subjects you've already learned")

    if "subject_suggestions" not in st.session_state:
        already = scoring.get_learned_subjects_for_topic(sessions, topic["id"])
        with st.spinner("Generating subjects with Gemini…"):
            subjects = scout.suggest_subjects(topic["name"], already)
        if not subjects:
            st.error("Could not generate subjects. Check your Gemini API key in Settings.")
            return
        st.session_state.subject_suggestions = subjects

    for i, subject in enumerate(st.session_state.subject_suggestions):
        if st.button(subject, key=f"subj_{i}", use_container_width=True):
            st.session_state.chosen_subject = subject
            st.session_state.learn_step = "learning"
            st.session_state.pop("current_video", None)
            st.session_state.pop("current_resources", None)
            st.rerun()


def _step_learning(sessions: list):
    topic = st.session_state.chosen_topic
    subject = st.session_state.chosen_subject

    if st.button("← Back to subjects"):
        st.session_state.learn_step = "subject_select"
        st.rerun()

    st.subheader(subject)
    st.caption(f"Topic: {topic['name']}")
    st.markdown("---")

    # Video
    st.markdown("### Watch (30-45 min)")
    if "current_video" not in st.session_state:
        with st.spinner("Finding best YouTube video…"):
            video = yt_client.find_video(subject, topic["name"])
        st.session_state.current_video = video
    else:
        video = st.session_state.current_video

    if video:
        st.video(video["url"])
        st.caption(f"**{video['title']}** · {video['channel']} · {video['duration_str']}")
    else:
        st.warning("No suitable video found via API. Search manually:")
        q = f"{subject} {topic['name']}"
        yt_url = f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}"
        st.markdown(f"[Search YouTube for this subject]({yt_url})")

    st.markdown("---")

    # Reading resources
    st.markdown("### Read (free / open access)")
    st.caption("_Links are AI-suggested — verify before citing_")
    if "current_resources" not in st.session_state:
        with st.spinner("Finding reading resources…"):
            resources = scout.suggest_resources(topic["name"], subject)
        st.session_state.current_resources = resources
    else:
        resources = st.session_state.current_resources

    if resources:
        for r in resources:
            st.markdown(f"- [{r.get('title', r.get('url', ''))}]({r.get('url', '#')})")
    else:
        st.info("No reading resources found. Try searching arXiv or Google Scholar.")

    st.markdown("---")

    # Already completed check
    already_done = any(
        s.get("subject") == subject and s.get("topic_id") == topic["id"] and s.get("completed")
        for s in sessions
    )
    if already_done:
        st.success("You already completed this subject! Pick a different one or mark it again.")
        if st.button("Choose a different subject"):
            st.session_state.learn_step = "subject_select"
            st.rerun()
    else:
        if st.button("✅ Mark as Learned", type="primary", use_container_width=True):
            _mark_learned(topic, subject, video, resources)
            st.session_state.learn_step = "topic_select"
            st.session_state.pop("subject_suggestions", None)
            st.balloons()
            st.success(f"Great work! '{subject}' recorded.")
            st.rerun()


def page_learn():
    user_data = get_user_data()
    sessions = user_data.get("sessions", [])
    all_topics = get_all_topics(user_data)

    if not all_topics:
        st.warning("No topics configured. Add topics in Settings.")
        return

    step = st.session_state.get("learn_step", "topic_select")
    if step == "topic_select":
        _step_topic_select(all_topics, sessions)
    elif step == "subject_select":
        _step_subject_select(sessions)
    elif step == "learning":
        _step_learning(sessions)

# ── My Progress page ───────────────────────────────────────────────────────────

def page_progress():
    user_data = get_user_data()
    sessions = user_data.get("sessions", [])
    monthly_stats = user_data.get("monthly_stats", {})

    today = date.today()
    yr, mo = today.year, today.month
    key = f"{yr}-{mo:02d}"

    month_sessions = scoring.get_month_sessions(sessions, yr, mo)
    n_learned = len(month_sessions)
    score = scoring.compute_monthly_score(n_learned)
    won = scoring.did_win_month(n_learned)
    streak = scoring.compute_streak(sessions)

    st.title("My Progress")
    st.subheader(today.strftime("%B %Y"))

    c1, c2, c3 = st.columns(3)
    c1.metric("Subjects Learned", n_learned)
    c2.metric("Monthly Score", f"{score:.1f} / 10")
    status = "WON 🎉" if won else "In Progress"
    c3.metric("Status", status)

    progress_val = min(1.0, n_learned / 15)
    st.progress(progress_val, text=f"{n_learned} / 15 subjects to WIN this month")
    st.metric("Current Streak", f"{streak} day{'s' if streak != 1 else ''} 🔥")

    # Monthly history chart (last 6 months)
    st.subheader("Monthly History")
    chart_rows = []
    for i in range(5, -1, -1):
        m = mo - i
        y = yr
        while m <= 0:
            m += 12
            y -= 1
        k = f"{y}-{m:02d}"
        n = monthly_stats.get(k, {}).get("subjects_learned", 0)
        label = date(y, m, 1).strftime("%b %Y")
        chart_rows.append({"Month": label, "Subjects": n})

    df = pd.DataFrame(chart_rows).set_index("Month")
    st.bar_chart(df)

    # Recent sessions list
    st.subheader("Recent Sessions")
    completed = sorted(
        [s for s in sessions if s.get("completed")],
        key=lambda s: s.get("completed_at", s.get("date", "")),
        reverse=True,
    )[:25]

    if not completed:
        st.info("No sessions recorded yet. Start learning!")
    else:
        for s in completed:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{s['subject']}**  \n{s['topic_name']}")
            c2.caption(s["date"])

# ── Settings page ─────────────────────────────────────────────────────────────

def page_settings():
    user_data = get_user_data()

    st.title("Settings")

    # ── Topic manager ──────────────────────────────────────────────────────────
    st.subheader("Learning Topics")

    try:
        default_topics = storage.load_topics()
    except Exception:
        default_topics = []

    custom_topics = user_data.get("custom_topics", [])

    st.markdown("**Built-in topics**")
    for t in default_topics:
        st.markdown(f"- {t['name']}")

    if custom_topics:
        st.markdown("**Your custom topics**")
        for i, t in enumerate(list(custom_topics)):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"- {t['name']}")
            if c2.button("Delete", key=f"del_topic_{i}"):
                custom_topics.pop(i)
                user_data["custom_topics"] = custom_topics
                save_user_data(user_data)
                st.rerun()

    st.markdown("**Add a new topic**")
    with st.form("add_topic_form", clear_on_submit=True):
        new_name = st.text_input("Topic name", placeholder="e.g. Quantum Computing basics")
        if st.form_submit_button("Add Topic", type="primary"):
            if new_name.strip():
                slug = re.sub(r"[^a-z0-9]+", "_", new_name.strip().lower())[:30]
                custom_topics.append({"id": slug, "name": new_name.strip(), "active": True})
                user_data["custom_topics"] = custom_topics
                save_user_data(user_data)
                st.success(f"Added: {new_name.strip()}")
                st.rerun()

    # ── API status ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("API Status")

    if st.button("Test all connections"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            try:
                from google import genai as _g
                _g.Client(api_key=st.secrets["GEMINI_API_KEY"]).models.generate_content(
                    model="gemini-2.0-flash", contents="ping"
                )
                st.success("Gemini ✓")
            except Exception as e:
                st.error(f"Gemini ✗\n{e}")

        with c2:
            try:
                from googleapiclient.discovery import build as _build
                svc = _build("youtube", "v3", developerKey=st.secrets["YOUTUBE_API_KEY"])
                svc.search().list(q="test", type="video", maxResults=1, part="id").execute()
                st.success("YouTube ✓")
            except Exception as e:
                st.error(f"YouTube ✗\n{e}")

        with c3:
            try:
                storage.load()
                st.success("GitHub ✓")
            except Exception as e:
                st.error(f"GitHub ✗\n{e}")

        with c4:
            groq_key = st.secrets.get("GROQ_API_KEY", "")
            if groq_key:
                try:
                    from groq import Groq as _Groq
                    _Groq(api_key=groq_key).chat.completions.create(
                        messages=[{"role": "user", "content": "ping"}],
                        model="llama-3.1-8b-instant",
                        max_tokens=5,
                    )
                    st.success("Groq ✓")
                except Exception as e:
                    st.error(f"Groq ✗\n{e}")
            else:
                st.info("Groq not configured")

    # ── Data export ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Data")
    st.download_button(
        label="Export my data (JSON)",
        data=json.dumps(user_data, indent=2),
        file_name="daily_learner_data.json",
        mime="application/json",
    )

# ── Sidebar + routing ──────────────────────────────────────────────────────────

user_data = get_user_data()
sessions = user_data.get("sessions", [])
streak = scoring.compute_streak(sessions)

yr, mo = date.today().year, date.today().month
n_this_month = len(scoring.get_month_sessions(sessions, yr, mo))

with st.sidebar:
    st.title("📚 Daily Learner")
    st.caption(date.today().strftime("%B %d, %Y"))
    st.metric("Streak", f"{streak} days {'🔥' if streak > 0 else ''}")
    st.metric("This month", f"{n_this_month} subjects")
    st.markdown("---")
    page = st.radio(
        "Navigate",
        ["Learn Today", "My Progress", "Settings"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if st.button("Logout", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
    st.markdown("---")
    st.caption("© Dr. Diptanil Debbarma")

if "learn_step" not in st.session_state:
    st.session_state.learn_step = "topic_select"

if page == "Learn Today":
    page_learn()
elif page == "My Progress":
    page_progress()
elif page == "Settings":
    page_settings()
