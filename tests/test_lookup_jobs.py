import json
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


JUDITH = {"youtube_id": "Cp31A_iqoDw", "title": "Judith", "channel": "A Perfect Circle", "duration": 246}
ALBUM_ID = "OLAK5uy_nc6afxSnmK8OFML8dF9q_0D1MBMXsGnL4"


def everything(songs=(), albums=(), artists=(), top=None):
    return {"songs": list(songs), "albums": list(albums), "artists": list(artists), "top": top}


def test_search_job_runs_caches_and_remembers(friend, monkeypatch):
    calls = []

    def fake_search(query):
        calls.append(query)
        return everything([JUDITH], albums=[{"playlist_id": ALBUM_ID, "title": "Mer de Noms"}],
                          artists=[{"name": "A Perfect Circle"}], top="song")

    monkeypatch.setattr(musicSearch, "search_everything", fake_search)
    state, job_id = lookupJobs.start_search(friend["friend_id"], "all", "Judith")
    assert state == "queued"
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "done" and job["results"][0]["source"] == "search"
    assert job["albums"][0]["title"] == "Mer de Noms" and job["artists"][0]["name"] == "A Perfect Circle"
    assert job["top"] == "song"
    assert lookupJobs.served_song(friend["friend_id"], "Cp31A_iqoDw")

    state, payload = lookupJobs.start_search(friend["friend_id"], "all", "judith")
    assert state == "done" and len(calls) == 1  # served from cache
    assert payload["albums"] and payload["artists"] and payload["top"] == "song"


def test_search_with_only_albums_is_not_empty(friend, monkeypatch):
    monkeypatch.setattr(musicSearch, "search_everything",
                        lambda q: everything(albums=[{"playlist_id": ALBUM_ID, "title": "Mer de Noms"}]))
    _, job_id = lookupJobs.start_search(friend["friend_id"], "all", "mer de noms")
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "done" and job["results"] == [] and len(job["albums"]) == 1


def test_opening_an_album_lists_its_tracks(friend, monkeypatch):
    urls = []

    def fake_tracks(url):
        urls.append(url)
        return [dict(JUDITH, album="Mer de Noms", track_number=3)]

    monkeypatch.setattr(musicSearch, "list_playlist_tracks", fake_tracks)
    _, job_id = lookupJobs.start_search(friend["friend_id"], "album", ALBUM_ID)
    job = wait_for(job_id, friend["friend_id"])
    assert urls == [f"https://music.youtube.com/playlist?list={ALBUM_ID}"]
    assert job["results"][0]["source"] == "ytm_album" and job["results"][0]["track_number"] == 3
    assert lookupJobs.served_song(friend["friend_id"], "Cp31A_iqoDw")


def test_album_mode_only_takes_album_ids(friend):
    for bad in ("Mer de Noms", "PLx250SW8TQakp4PLTltn3P3oTAMhl9SgH", "OLAK5uy_ x"):
        with pytest.raises(lookupJobs.LookupRefused) as refused:
            lookupJobs.start_search(friend["friend_id"], "album", bad)
        assert refused.value.status == 400


def test_opening_an_artist_lists_their_songs(friend, monkeypatch):
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, limit=20: [
        JUDITH, dict(JUDITH, youtube_id="d" * 11, channel="Someone Else")])
    _, job_id = lookupJobs.start_search(friend["friend_id"], "artist", "A Perfect Circle")
    job = wait_for(job_id, friend["friend_id"])
    assert [s["youtube_id"] for s in job["results"]] == ["Cp31A_iqoDw"]


def test_friend_rate_limit_applies_to_cache_misses(friend, monkeypatch):
    monkeypatch.setattr(lookupJobs, "FRIEND_LIMITS", dict(lookupJobs.FRIEND_LIMITS, search=[(3600, 1)]))
    monkeypatch.setattr(musicSearch, "search_everything", lambda q: everything())
    lookupJobs.start_search(friend["friend_id"], "all", "first")
    with pytest.raises(lookupJobs.LookupRefused) as refused:
        lookupJobs.start_search(friend["friend_id"], "all", "second")
    assert refused.value.status == 429 and refused.value.retry_after


def test_server_budget_exhaustion_fails_job(friend, monkeypatch):
    monkeypatch.setattr(lookupJobs, "SERVER_YTDLP_LIMITS", [(86400, 0)])
    monkeypatch.setattr(musicSearch, "search_everything", lambda q: pytest.fail("yt-dlp must not run"))
    _, job_id = lookupJobs.start_search(friend["friend_id"], "all", "anything")
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "error" and "tomorrow" in job["error"]


def test_empty_results_are_an_error_not_cached(friend, monkeypatch):
    monkeypatch.setattr(musicSearch, "search_everything", lambda q: everything())
    _, job_id = lookupJobs.start_search(friend["friend_id"], "all", "zzzz")
    assert wait_for(job_id, friend["friend_id"])["status"] == "error"
    assert suggestionsRepo.cache_get(lookupJobs.search_cache_key("all", "zzzz"), 60) is None


def test_search_everything_sorts_one_search_into_categories(monkeypatch):
    mixed = [
        {"category": "Top result", "resultType": "artist", "artists": [{"name": "Daft Punk", "id": "UC1"}],
         "thumbnails": [{"url": "https://lh3.googleusercontent.com/a=w60", "width": 60},
                        {"url": "https://lh3.googleusercontent.com/a=w120", "width": 120}]},
        {"resultType": "song", "title": "Da Funk", "videoId": "32J7bZHva9M"},
        {"resultType": "video", "title": "Da Funk (Official Video)", "videoId": "mmi60Bd4jSs"},
        {"resultType": "album", "title": "Discovery", "type": "Album", "year": "2001",
         "playlistId": ALBUM_ID, "artists": [{"name": "Daft Punk"}],
         "thumbnails": [{"url": "https://evil.example/x.jpg", "width": 60}]},
        {"resultType": "album", "title": "No playlist", "playlistId": None},
        {"resultType": "artist", "artist": "Daft Punk", "radioId": "RD1"},  # same as the top result
        {"resultType": "artist", "artist": "Pentatonix", "radioId": "RD2"},
        {"resultType": "artist", "artist": "daft punk lover1177"},  # a fan channel, no radio
        {"resultType": "playlist", "title": "Daft Punk mix"},
    ]
    monkeypatch.setattr(musicSearch, "_ytmusic", lambda: type("Y", (), {"search": lambda self, q: mixed})())
    monkeypatch.setattr(musicSearch, "search_songs", lambda q, limit: [JUDITH])
    found = musicSearch.search_everything("daft punk")
    assert found["top"] == "artist"
    assert found["songs"] == [JUDITH]
    assert found["albums"] == [{"playlist_id": ALBUM_ID, "title": "Discovery", "artist": "Daft Punk",
                                "year": "2001", "type": "Album", "thumbnail": None}]
    assert found["artists"] == [
        {"name": "Daft Punk", "thumbnail": "https://lh3.googleusercontent.com/a=w120"},
        {"name": "Pentatonix", "thumbnail": None},
    ]


def test_spotify_links_need_no_keys(friend, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.setattr(spotifyClient, "playlist_tracks", lambda pid, limit: ([], False))
    state, job_id = lookupJobs.start_resolve(friend["friend_id"], "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    assert state == "queued"
    assert "no songs" in wait_for(job_id, friend["friend_id"])["error"]


def test_spotify_playlist_is_matched_track_by_track(friend, monkeypatch):
    tracks = [
        {"sp_track_id": "t1", "sp_title": "Judith - 2004 Remaster", "sp_artist": "A Perfect Circle", "sp_album": "Mer de Noms", "sp_duration_seconds": 246},
        {"sp_track_id": "t2", "sp_title": "Nothing Like It", "sp_artist": "Nobody", "sp_album": "X", "sp_duration_seconds": 200},
    ]
    queries = []

    def fake_search(query, limit):
        queries.append(query)
        return [] if "Nobody" in query else [
            {"youtube_id": "c" * 11, "title": "Judith", "channel": "A Perfect Circle - Topic", "duration": 246}]

    monkeypatch.setattr(spotifyClient, "playlist_tracks", lambda pid, limit: (tracks, True))
    monkeypatch.setattr(musicSearch, "search_songs", fake_search)
    _, job_id = lookupJobs.start_resolve(friend["friend_id"], "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
    job = wait_for(job_id, friend["friend_id"])
    assert job["status"] == "done"
    assert queries[0] == "A Perfect Circle - Judith"  # edition suffix left out of the search
    assert [s["youtube_id"] for s in job["results"]] == ["c" * 11]
    assert job["results"][0]["album"] == "Mer de Noms" and job["results"][0]["source"] == "spotify"
    assert "Nothing Like It" in job["note"] and "first 100" in job["note"]


def embed_page(entity):
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_embed_playlist_parsing(monkeypatch):
    track_list = [
        {"uri": "spotify:track:1", "title": "Bass Persuades", "subtitle": "Miley Cyrus, Someone", "duration": 202460, "entityType": "track"},
        {"uri": "spotify:episode:2", "title": "A podcast", "subtitle": "Show", "duration": 1, "entityType": "episode"},
        {"uri": "spotify:track:3", "title": "", "subtitle": "x", "duration": 1},
    ]
    html = embed_page({"type": "playlist", "name": "Mix", "trackList": track_list})
    monkeypatch.setattr(spotifyClient, "_fetch_entity", lambda kind, sid: spotifyClient.parse_entity(html))
    tracks, truncated = spotifyClient.playlist_tracks("p", limit=10)
    assert tracks == [{"sp_track_id": "1", "sp_title": "Bass Persuades", "sp_artist": "Miley Cyrus, Someone",
                       "sp_album": None, "sp_duration_seconds": 202}]
    assert not truncated

    full = embed_page({"type": "playlist", "name": "Big", "trackList": [dict(track_list[0], uri=f"spotify:track:{n}") for n in range(100)]})
    monkeypatch.setattr(spotifyClient, "_fetch_entity", lambda kind, sid: spotifyClient.parse_entity(full))
    tracks, truncated = spotifyClient.playlist_tracks("p", limit=100)
    assert len(tracks) == 100 and truncated  # embed pages stop at 100


def test_embed_album_and_track_parsing(monkeypatch):
    pages = {
        "album": embed_page({"type": "album", "name": "The Dark Side of the Moon", "trackList": [
            {"uri": "spotify:track:a", "title": "Breathe (In the Air)", "subtitle": "Pink Floyd", "duration": 169000}]}),
        "track": embed_page({"type": "track", "id": "t", "name": "Knights of Cydonia",
                             "artists": [{"name": "Muse"}], "duration": 366213}),
    }
    monkeypatch.setattr(spotifyClient, "_fetch_entity", lambda kind, sid: spotifyClient.parse_entity(pages[kind]))
    tracks, _ = spotifyClient.album_tracks("a", limit=100)
    assert tracks[0]["sp_album"] == "The Dark Side of the Moon" and tracks[0]["sp_artist"] == "Pink Floyd"
    tracks, _ = spotifyClient.single_track("t")
    assert tracks == [{"sp_track_id": "t", "sp_title": "Knights of Cydonia", "sp_artist": "Muse",
                       "sp_album": None, "sp_duration_seconds": 366}]


@pytest.mark.parametrize("html", ["<html>nothing here</html>", embed_page(None), embed_page({"name": "no type"})])
def test_missing_or_private_links_raise_friendly_error(html):
    with pytest.raises(spotifyClient.SpotifyError):
        spotifyClient.parse_entity(html)
