"""Base interface for music providers.

A provider only *decides what to play and returns a structured payload*; it never
plays audio (the frontend/Electron embed does that). Concrete providers (e.g.
YouTube) subclass this and implement the async methods.
"""


ALLOWED_MODES = {"artist", "song", "genre", "mood", "random", "search"}


def normalize_mode(mode):
    mode = str(mode or "").strip().lower()
    return mode if mode in ALLOWED_MODES else "search"


class MusicProvider:
    """Common base for music providers.

    Concrete providers receive a ``preferences_manager`` by injection so that the
    ``random``/``mood`` modes can resolve against the user's saved preferences
    without coupling the provider to storage details.
    """

    name = "base"

    def __init__(self, preferences_manager=None):
        self.preferences_manager = preferences_manager

    async def search(self, query, mode="search"):  # pragma: no cover - abstract
        raise NotImplementedError

    async def play(self, query, mode="search"):  # pragma: no cover - abstract
        raise NotImplementedError

    def status(self):
        return {"provider": self.name}

    def preferences(self):
        if self.preferences_manager is None:
            return {}
        return self.preferences_manager.get_preferences()

    def random_from_preferences(self):
        """Returns a ``{"query": str, "mode": str}`` chosen from saved preferences.

        Falls back to a sensible default when no preferences are configured."""
        if self.preferences_manager is not None:
            choice = self.preferences_manager.choose_random_query()
            if choice and choice.get("query"):
                return choice
        return {"query": "musica", "mode": "search"}
