"""YouTube music provider.

- With ``JARVIS_YOUTUBE_API_KEY`` it queries the official YouTube Data API and
  returns a concrete ``video_id`` + ``embed_url`` (the frontend can auto-play it).
- Without an API key it returns a clean fallback: a structured search query plus a
  YouTube *results* URL the frontend can open. No scraping, ever.
"""

import os
from urllib.parse import quote_plus

try:  # pragma: no cover - relative vs absolute import depending on entry point
    from .music_provider import MusicProvider, normalize_mode
except ImportError:  # pragma: no cover
    from music_provider import MusicProvider, normalize_mode


YOUTUBE_SEARCH_API = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_RESULTS_URL = "https://www.youtube.com/results?search_query="
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v="
YOUTUBE_EMBED_URL = "https://www.youtube.com/embed/"


class YouTubeMusicProvider(MusicProvider):
    name = "youtube"

    def __init__(self, preferences_manager=None, api_key=None, http_timeout=8):
        super().__init__(preferences_manager=preferences_manager)
        self._api_key = api_key
        self.http_timeout = http_timeout

    # ------------------------------------------------------------------ helpers
    @property
    def api_key(self):
        # Read lazily so changing the env at runtime is honored, but allow an
        # explicit constructor override (handy for tests).
        if self._api_key is not None:
            return self._api_key
        return os.getenv("JARVIS_YOUTUBE_API_KEY", "").strip()

    def has_api_key(self):
        return bool(self.api_key)

    def _build_query(self, query, mode):
        mode = normalize_mode(mode)
        text = str(query or "").strip()

        if mode == "random" or (mode == "search" and not text):
            choice = self.random_from_preferences()
            text = str(choice.get("query") or "").strip()
            mode = normalize_mode(choice.get("mode") or "search")

        if mode == "artist":
            return f"{text} music", mode
        if mode == "song":
            return text or "musica", mode
        if mode == "genre":
            return f"{text} music mix", mode
        if mode == "mood":
            mood = text or "concentracion"
            return f"musica para {mood}", mode
        # search / fallback
        return (text or "musica"), mode

    def _fallback_result(self, search_query, mode):
        return {
            "success": True,
            "provider": self.name,
            "mode": mode,
            "query": search_query,
            "video_id": None,
            "title": "Busqueda de YouTube",
            "url": f"{YOUTUBE_RESULTS_URL}{quote_plus(search_query)}",
            "embed_url": None,
            "fallback": True,
        }

    def _video_result(self, search_query, mode, video_id, title):
        return {
            "success": True,
            "provider": self.name,
            "mode": mode,
            "query": search_query,
            "video_id": video_id,
            "title": title or search_query,
            "url": f"{YOUTUBE_WATCH_URL}{video_id}",
            "embed_url": f"{YOUTUBE_EMBED_URL}{video_id}",
            "fallback": False,
        }

    # ------------------------------------------------------------------- public
    async def search(self, query, mode="search"):
        search_query, resolved_mode = self._build_query(query, mode)
        if not self.has_api_key():
            return self._fallback_result(search_query, resolved_mode)

        try:
            video_id, title = await self._api_search(search_query)
        except Exception as exc:
            result = self._fallback_result(search_query, resolved_mode)
            result["error"] = f"YouTube API error: {str(exc)[:200]}"
            return result

        if not video_id:
            return self._fallback_result(search_query, resolved_mode)
        return self._video_result(search_query, resolved_mode, video_id, title)

    async def play(self, query, mode="search"):
        # Playback decision is identical to search; the frontend does the playing.
        return await self.search(query, mode)

    async def _api_search(self, search_query):
        """Calls the YouTube Data API and returns ``(video_id, title)``.

        Network is fully isolated here so the fallback path needs no connection."""
        import aiohttp

        params = {
            "part": "snippet",
            "type": "video",
            "maxResults": "1",
            "videoCategoryId": "10",  # Music
            "q": search_query,
            "key": self.api_key,
        }
        timeout = aiohttp.ClientTimeout(total=self.http_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(YOUTUBE_SEARCH_API, params=params) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.json()

        items = data.get("items") if isinstance(data, dict) else None
        if not items:
            return None, None
        first = items[0] or {}
        video_id = (first.get("id") or {}).get("videoId")
        title = (first.get("snippet") or {}).get("title")
        return video_id, title
