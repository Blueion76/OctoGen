"""Tests for NavidromeAPI.get_seed_songs() seed-fallback behavior.

Locks in the bug-driven feature: when the starred-song set is too small for
Gemini's 1024-token context-cache floor, augment with most-played-album songs
until SEED_FALLBACK_TARGET is reached.
"""

from unittest.mock import patch, MagicMock

from octogen.api.navidrome import NavidromeAPI


def _make_api(min_threshold=50, target=500, album_count=100):
    """Construct a NavidromeAPI with a mocked ratings cache and minimal config."""
    api = NavidromeAPI.__new__(NavidromeAPI)
    api.url = "http://navidrome.test"
    api.username = "u"
    api.password = "p"
    api.session = MagicMock()
    api.ratings_cache = MagicMock()
    api.album_batch_size = 500
    api.max_albums = 10000
    api.scan_timeout = 60
    api.seed_fallback_min = min_threshold
    api.seed_fallback_target = target
    api.seed_fallback_album_count = album_count
    return api


def _starred(n):
    return [
        {"id": f"s{i}", "title": f"t{i}", "artist": "a", "album": "x", "genre": "g"}
        for i in range(n)
    ]


def _album_songs(album_id, count, start=1000):
    return [
        {"id": f"{album_id}-song{i}", "title": f"st{i}", "artist": "aa", "album": "alb", "genre": "g"}
        for i in range(start, start + count)
    ]


class TestSeedFallbackThreshold:
    def test_returns_starred_unchanged_when_above_threshold(self):
        api = _make_api(min_threshold=50)
        with patch.object(api, "get_starred_songs", return_value=_starred(60)):
            songs = api.get_seed_songs()
        assert len(songs) == 60
        assert all(s["id"].startswith("s") for s in songs)

    def test_augments_when_below_threshold(self):
        api = _make_api(min_threshold=50, target=100)
        starred = _starred(10)
        albums_payload = {
            "albumList2": {
                "album": [
                    {"id": "alb1", "name": "A1", "artist": "AA"},
                    {"id": "alb2", "name": "A2", "artist": "BB"},
                ]
            }
        }
        with patch.object(api, "get_starred_songs", return_value=starred), \
             patch.object(api, "_request", return_value=albums_payload), \
             patch.object(api, "_fetch_albums_songs_parallel", new=MagicMock()) as fetcher:
            # MagicMock can't be awaited; replace with an AsyncMock-like wrapper.
            async def _fake(album_ids):
                return [_album_songs(aid, 30, start=1000) for aid in album_ids]
            fetcher.side_effect = lambda ids: _fake(ids)
            # asyncio.run will run our coroutine
            songs = api.get_seed_songs()
        assert len(songs) > 10  # augmented
        # Original starred IDs are preserved at the front
        assert [s["id"] for s in songs[:10]] == [f"s{i}" for i in range(10)]


class TestSeedFallbackDedup:
    def test_deduplicates_against_starred(self):
        api = _make_api(min_threshold=50, target=20)
        starred = _starred(5)
        # Album song shares an id with starred song s0
        albums_payload = {"albumList2": {"album": [{"id": "alb1", "name": "A1", "artist": "AA"}]}}

        async def _fake(album_ids):
            # Return one duplicate (s0) and several unique
            dup = {"id": "s0", "title": "dup", "artist": "x", "album": "x", "genre": "g"}
            uniq = _album_songs("alb1", 5, start=2000)
            return [[dup] + uniq]

        with patch.object(api, "get_starred_songs", return_value=starred), \
             patch.object(api, "_request", return_value=albums_payload), \
             patch.object(api, "_fetch_albums_songs_parallel", side_effect=_fake):
            songs = api.get_seed_songs()
        ids = [s["id"] for s in songs]
        assert ids.count("s0") == 1
        # Should have at most starred (5) + 5 unique album songs
        assert len(songs) == 10


class TestSeedFallbackTargetCap:
    def test_stops_at_target(self):
        api = _make_api(min_threshold=50, target=12)
        starred = _starred(2)
        albums_payload = {
            "albumList2": {
                "album": [
                    {"id": "alb1", "name": "A1", "artist": "AA"},
                    {"id": "alb2", "name": "A2", "artist": "BB"},
                ]
            }
        }

        async def _fake(album_ids):
            return [_album_songs(aid, 50, start=3000) for aid in album_ids]

        with patch.object(api, "get_starred_songs", return_value=starred), \
             patch.object(api, "_request", return_value=albums_payload), \
             patch.object(api, "_fetch_albums_songs_parallel", side_effect=_fake):
            songs = api.get_seed_songs()
        assert len(songs) == 12


class TestSeedFallbackFailure:
    def test_returns_starred_when_augmentation_raises(self):
        api = _make_api(min_threshold=50, target=100)
        starred = _starred(10)
        with patch.object(api, "get_starred_songs", return_value=starred), \
             patch.object(api, "_request", side_effect=KeyError("bad shape")):
            songs = api.get_seed_songs()
        # Augmentation failed but starred songs are still returned
        assert songs == starred


class TestParallelFetchResilience:
    """_fetch_albums_songs_parallel uses return_exceptions=True so a single
    album failure does not collapse the whole batch."""

    def test_one_failure_does_not_cancel_others(self):
        import asyncio as _asyncio

        api = _make_api()

        async def fake_one(session, aid):
            if aid == "bad":
                raise RuntimeError("boom")
            return [{"id": f"{aid}-1", "title": "t", "artist": "a", "album": "a", "genre": "g"}]

        with patch.object(api, "_fetch_album_songs_async", side_effect=fake_one):
            results = _asyncio.run(api._fetch_albums_songs_parallel(["good", "bad", "good2"]))

        assert results[0] == [{"id": "good-1", "title": "t", "artist": "a", "album": "a", "genre": "g"}]
        assert results[1] == []  # failure replaced with empty list
        assert results[2] == [{"id": "good2-1", "title": "t", "artist": "a", "album": "a", "genre": "g"}]
