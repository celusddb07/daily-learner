import json
import re
import time

from google import genai
from groq import Groq


_SUBJECT_PROMPT = """\
You are a study curriculum designer for a working professional.

Topic area: {topic_name}

Subjects already studied (DO NOT suggest these again):
{already_learned}

Generate exactly 6 specific, learnable subjects within this topic area.
Each subject should be:
- Specific enough to cover in a 30-45 minute video session
- Technically precise, using correct domain terminology
- Not already in the "already studied" list above

Output ONLY a numbered list, one subject per line, no explanations, no preamble:
1. <subject>
2. <subject>
3. <subject>
4. <subject>
5. <subject>
6. <subject>
"""

_RESOURCES_PROMPT = """\
You are a research librarian specialising in open-access technical education.

Topic: {topic_name}
Subject: {subject}

Provide exactly 4 free, publicly accessible learning resources for this subject.
Prefer: arXiv papers, Wikipedia technical articles, IEEE open-access, 3GPP/ETSI specs,
EPO/UPC official documentation, or reputable university lecture notes.

IMPORTANT: Only include URLs you are certain exist. Do not invent URLs.

Output ONLY a JSON array with no preamble or explanation:
[
  {{"title": "...", "url": "https://..."}},
  {{"title": "...", "url": "https://..."}}
]
"""


class ContentScout:
    def __init__(self, gemini_key: str, groq_key: str = ""):
        self._gemini = genai.Client(api_key=gemini_key)
        self._groq = Groq(api_key=groq_key) if groq_key else None

    def _call_gemini(self, prompt: str) -> str:
        resp = self._gemini.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return resp.text.strip()

    def _call_groq(self, prompt: str) -> str:
        if self._groq is None:
            raise RuntimeError("Groq not configured")
        completion = self._groq.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        return completion.choices[0].message.content.strip()

    def _generate(self, prompt: str) -> str:
        try:
            return self._call_gemini(prompt)
        except Exception as e:
            print(f"[Gemini] failed: {e} — trying Groq...")
            try:
                return self._call_groq(prompt)
            except Exception as e2:
                print(f"[Groq] also failed: {e2}")
                raise

    def suggest_subjects(self, topic_name: str, already_learned: list[str]) -> list[str]:
        already_block = "\n".join(f"- {s}" for s in already_learned) if already_learned else "(none)"
        prompt = _SUBJECT_PROMPT.format(topic_name=topic_name, already_learned=already_block)
        text = self._generate(prompt)
        subjects = re.findall(r"^\d+\.\s+(.+)$", text, re.MULTILINE)
        return [s.strip() for s in subjects if s.strip()]

    def suggest_resources(self, topic_name: str, subject: str) -> list[dict]:
        prompt = _RESOURCES_PROMPT.format(topic_name=topic_name, subject=subject)
        text = self._generate(prompt)
        return _parse_json_resources(text, self._groq, prompt)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_json_resources(text: str, groq_client, original_prompt: str) -> list[dict]:
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        if groq_client is None:
            return []
        # One retry via Groq
        try:
            groq_completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": original_prompt}],
                model="llama-3.3-70b-versatile",
            )
            retry_text = groq_completion.choices[0].message.content.strip()
            return json.loads(_strip_fences(retry_text))
        except Exception:
            return []
