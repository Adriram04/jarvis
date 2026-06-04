from music_preferences_manager import MusicPreferencesManager


def _manager(tmp_path):
    return MusicPreferencesManager(tmp_path / "music_preferences.json")


def test_defaults_have_expected_shape(tmp_path):
    prefs = _manager(tmp_path).get_preferences()
    assert prefs["favorite_artists"] == []
    assert prefs["favorite_genres"] == []
    assert set(prefs["moods"].keys()) == {"programar", "entrenar", "relajarse"}
    assert prefs["history"] == []
    assert 0 <= prefs["default_volume"] <= 100


def test_update_accepts_comma_string_and_list(tmp_path):
    manager = _manager(tmp_path)
    updated = manager.update_preferences({
        "favorite_artists": "Estopa, Queen, Estopa",  # dedupe
        "favorite_genres": ["rock", "lofi"],
        "moods": {"programar": "lofi, focus", "entrenar": [], "relajarse": ["chill"]},
        "default_volume": 70,
    })
    assert updated["favorite_artists"] == ["Estopa", "Queen"]
    assert updated["favorite_genres"] == ["rock", "lofi"]
    assert updated["moods"]["programar"] == ["lofi", "focus"]
    assert updated["default_volume"] == 70


def test_update_persists_across_instances(tmp_path):
    path = tmp_path / "music_preferences.json"
    MusicPreferencesManager(path).update_preferences({"favorite_artists": "Estopa"})
    reloaded = MusicPreferencesManager(path).get_preferences()
    assert reloaded["favorite_artists"] == ["Estopa"]


def test_add_history_prepends_and_caps(tmp_path):
    manager = MusicPreferencesManager(tmp_path / "m.json", max_history=3)
    for i in range(5):
        manager.add_history({"query": f"q{i}", "title": f"t{i}", "provider": "youtube", "fallback": True})
    history = manager.get_history()
    assert len(history) == 3
    assert history[0]["query"] == "q4"  # most recent first
    assert "played_at" in history[0]


def test_choose_random_query_uses_preferences(tmp_path):
    manager = _manager(tmp_path)
    manager.update_preferences({
        "favorite_artists": ["Estopa"],
        "favorite_genres": [],
        "moods": {"programar": [], "entrenar": [], "relajarse": []},
    })
    choice = manager.choose_random_query()
    assert choice["query"] == "Estopa"
    assert choice["mode"] == "artist"


def test_choose_random_query_empty_when_no_preferences(tmp_path):
    choice = _manager(tmp_path).choose_random_query()
    assert choice["query"] == ""
    assert choice["mode"] == "random"


def test_default_volume_clamped(tmp_path):
    manager = _manager(tmp_path)
    assert manager.update_preferences({"default_volume": 999})["default_volume"] == 100
    assert manager.update_preferences({"default_volume": -5})["default_volume"] == 0
