import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class YouTubeClient:
    def __init__(self, api_key: str):
        self._service = build("youtube", "v3", developerKey=api_key)

    def find_video(self, subject: str, topic_name: str) -> dict | None:
        query = f"{subject} {topic_name} explained"
        try:
            search_resp = self._service.search().list(
                q=query,
                type="video",
                videoDuration="long",   # >20 min
                relevanceLanguage="en",
                maxResults=10,
                part="id,snippet",
            ).execute()
        except HttpError as e:
            if e.resp.status == 403:
                return None  # quota exceeded
            raise

        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
        if not video_ids:
            return None

        details_resp = self._service.videos().list(
            id=",".join(video_ids),
            part="contentDetails,snippet",
        ).execute()

        # Prefer videos in the 20-65 minute range
        best = None
        for item in details_resp.get("items", []):
            minutes = _parse_duration_minutes(item["contentDetails"]["duration"])
            if 20 <= minutes <= 65:
                best = item
                break

        # Fall back to first result if none are in the preferred range
        if best is None and details_resp.get("items"):
            best = details_resp["items"][0]

        if best is None:
            return None

        vid_id = best["id"]
        snippet = best["snippet"]
        return {
            "video_id": vid_id,
            "title": snippet["title"],
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "duration_str": _format_duration(best["contentDetails"]["duration"]),
            "channel": snippet["channelTitle"],
        }


def _parse_duration_minutes(duration: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


def _format_duration(duration: str) -> str:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return "?"
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes} min"
