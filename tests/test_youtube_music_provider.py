import asyncio

from integrations.youtube_music_provider import YouTubeMusicProvider
from music_preferences_manager import MusicPreferencesManager


def _run(coro):
    return asyncio.run(coro)


def _provider(tmp_path, api_key=""):
    prefs = MusicPreferencesManager(tmp_path / "m.json")
    # api_key="" forces the fallback path regardless of the real environment.
    return YouTubeMusicProvider(preferences_manager=prefs, api_key=api_key), prefs


def test_build_query_per_mode(tmp_path):
    provider, _ = _provider(tmp_path)
    assert provider._build_query("Estopa", "artist") == ("Estopa music", "artist")
    assert provider._build_query("Bohemian", "song") == ("Bohemian", "song")
    assert provider._build_query("rock", "genre") == ("rock music mix", "genre")
    assert provider._build_query("programar", "mood") == ("musica para programar", "mood")
    assert provider._build_query("lofi beats", "search") == ("lofi beats", "search")


def test_no_api_key_returns_structured_fallback(tmp_path):
    provider, _ = _provider(tmp_path)
    result = _run(provider.play("Estopa", "artist"))
    assert result["success"] is True
    assert result["provider"] == "youtube"
    assert result["fallback"] is True
    assert result["video_id"] is None
    assert result["embed_url"] is None
    assert result["query"] == "Estopa music"
    assert result["url"].startswith("https://www.youtube.com/results?search_query=")
    assert "Estopa" in result["url"]


def test_random_mode_resolves_from_preferences(tmp_path):
    provider, prefs = _provider(tmp_path)
    prefs.update_preferences({"favorite_artists": ["Queen"]})
    result = _run(provider.play("", "random"))
    assert result["fallback"] is True
    # Resolved to the favorite artist, in artist mode → "Queen music".
    assert result["query"] == "Queen music"
    assert result["mode"] == "artist"


def test_search_without_text_falls_back_to_random(tmp_path):
    provider, prefs = _provider(tmp_path)
    prefs.update_preferences({"favorite_genres": ["rock"]})
    result = _run(provider.search("", "search"))
    assert result["success"] is True
    # Empty search resolves via preferences → genre "rock music mix".
    assert result["query"] == "rock music mix"


def test_has_api_key_reflects_constructor(tmp_path):
    provider, _ = _provider(tmp_path, api_key="")
    assert provider.has_api_key() is False
    provider2 = YouTubeMusicProvider(api_key="abc123")
    assert provider2.has_api_key() is True
