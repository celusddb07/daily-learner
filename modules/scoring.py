from datetime import date, timedelta


def compute_monthly_score(n_learned: int) -> float:
    return min(10.0, round(n_learned * 10 / 30, 1))


def did_win_month(n_learned: int) -> bool:
    return n_learned >= 15


def compute_streak(sessions: list) -> int:
    completed_dates = {s["date"] for s in sessions if s.get("completed")}
    if not completed_dates:
        return 0

    today = date.today()
    # Start from today if it has a session, else from yesterday
    check = today if today.isoformat() in completed_dates else today - timedelta(days=1)

    streak = 0
    while check.isoformat() in completed_dates:
        streak += 1
        check -= timedelta(days=1)
    return streak


def get_learned_subjects_for_topic(sessions: list, topic_id: str) -> list[str]:
    return [
        s["subject"]
        for s in sessions
        if s.get("completed") and s.get("topic_id") == topic_id
    ]


def get_month_sessions(sessions: list, year: int, month: int) -> list:
    key = f"{year}-{month:02d}"
    return [s for s in sessions if s.get("completed") and s.get("date", "").startswith(key)]
