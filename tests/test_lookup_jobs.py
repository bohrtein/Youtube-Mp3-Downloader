import time

import pytest

import core.lookupJobs as lookupJobs
import core.musicSearch as musicSearch
import core.spotifyClient as spotifyClient
import database.suggestionsRepo as suggestionsRepo


@pytest.fixture(autouse=True)
def fast_pacing(monkeypatch):
    monkeypatch.setattr(lookupJobs, "YTDLP_MIN_SPACING_SECONDS", 0)


def wait_for(job_id, friend_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = lookupJobs.get_job(job_id, friend_id)
        if job and job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_search_job_runs_caches_and_remembers(friend, monkeypatch):
    calls = []

    def fake_search(query, limit):
        calls.append(query)
        return [{"youtube_id": "Cp31A_iqoDw", "title": "Judith", "channel": "A Perfect Circle", "duration": 246}]

    monkeypatch.setattr(musicSearch, "search_songs", fake_search)
    state, job_id = lookupJobs.start_search(friend["friend_id"], "song", "Judith")
    assert state == "queued"
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "done" and job["results"][0]["source"] == "search"
    assert lookupJobs.served_song(friend["friend_id"], "Cp31A_iqoDw")

    state, payload = lookupJobs.start_search(friend["friend_id"], "song", "judith")
    assert state == "done" and len(calls) == 1  # served from cache


def test_friend_rate_limit_applies_to_cache_misses(friend, monkeypatch):
    monkeypatch.setattr(lookupJobs, "FRIEND_LIMITS", dict(lookupJobs.FRIEND_LIMITS, search=[(3600, 1)]))
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, n: [])
    lookupJobs.start_search(friend["friend_id"], "song", "first")
    with pytest.raises(lookupJobs.LookupRefused) as refused:
        lookupJobs.start_search(friend["friend_id"], "song", "second")
    assert refused.value.status == 429 and refused.value.retry_after


def test_server_budget_exhaustion_fails_job(friend, monkeypatch):
    monkeypatch.setattr(lookupJobs, "SERVER_YTDLP_LIMITS", [(86400, 0)])
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, n: pytest.fail("yt-dlp must not run"))
    _, job_id = lookupJobs.start_search(friend["friend_id"], "song", "anything")
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "error" and "tomorrow" in job["error"]


def test_empty_results_are_an_error_not_cached(friend, monkeypatch):
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, n: [])
    _, job_id = lookupJobs.start_search(friend["friend_id"], "song", "zzzz")
    assert wait_for(job_id, friend["friend_id"])["status"] == "error"
    assert suggestionsRepo.cache_get(lookupJobs.search_cache_key("song", "zzzz"), 60) is None


def test_spotify_links_need_configuration(friend, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(lookupJobs.LookupRefused):
        lookupJobs.start_resolve(friend["friend_id"], "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")


def test_spotify_playlist_is_matched_track_by_track(friend, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    tracks = [
        {"sp_track_id": "t1", "sp_title": "Judith", "sp_artist": "A Perfect Circle", "sp_album": "Mer de Noms", "sp_duration_seconds": 246},
        {"sp_track_id": "t2", "sp_title": "Nothing Like It", "sp_artist": "Nobody", "sp_album": "X", "sp_duration_seconds": 200},
    ]
    monkeypatch.setattr(spotifyClient, "playlist_tracks", lambda pid, limit: (tracks, False))
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, n: [] if "Nobody" in q else [
        {"youtube_id": "c" * 11, "title": "Judith", "channel": "A Perfect Circle - Topic", "duration": 246}])
    _, job_id = lookupJobs.start_resolve(friend["friend_id"], "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "done"
    assert [s["sp_title"] for s in job["results"]] == ["Judith"]
    assert job["results"][0]["album"] == "Mer de Noms" and job["results"][0]["source"] == "spotify"
    assert "Nothing Like It" in job["note"]


def test_spotify_track_parsing(monkeypatch):
    pages = {
        "/playlists/p/tracks": {"items": [
            {"track": {"type": "track", "id": "1", "name": "Judith", "duration_ms": 246500,
                       "artists": [{"name": "A Perfect Circle"}, {"name": "Guest"}], "album": {"name": "Mer de Noms"}}},
            {"track": {"type": "episode", "id": "2", "name": "A podcast"}},
            {"track": None},
        ], "next": "https://api.spotify.com/v1/next-page"},
        "https://api.spotify.com/v1/next-page": {"items": [
            {"track": {"type": "track", "id": "3", "name": "Orestes", "duration_ms": 289000,
                       "artists": [{"name": "A Perfect Circle"}], "album": {"name": "Mer de Noms"}}},
        ], "next": None},
    }
    monkeypatch.setattr(spotifyClient, "_api_get", lambda path, params=None: pages[path])
    tracks, truncated = spotifyClient.playlist_tracks("p", limit=10)
    assert not truncated
    assert tracks == [
        {"sp_track_id": "1", "sp_title": "Judith", "sp_artist": "A Perfect Circle", "sp_album": "Mer de Noms", "sp_duration_seconds": 246},
        {"sp_track_id": "3", "sp_title": "Orestes", "sp_artist": "A Perfect Circle", "sp_album": "Mer de Noms", "sp_duration_seconds": 289},
    ]
    tracks, truncated = spotifyClient.playlist_tracks("p", limit=1)
    assert len(tracks) == 1 and truncated
