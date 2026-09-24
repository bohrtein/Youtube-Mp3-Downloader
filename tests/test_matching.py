from pathlib import Path

import pytest

import core.approvedDownloads as approvedDownloads
import core.lookupJobs as lookupJobs
import core.musicSearch as musicSearch
import core.songMatch as songMatch
import core.suggestFlags as suggestFlags
import database.suggestionsRepo as suggestionsRepo
from tests.helpers import add_library_song


@pytest.mark.parametrize("title, artist, expected", [
    ("A Perfect Circle - Judith (Official Music Video)", "A Perfect Circle", "judith"),
    ("Judith", "A Perfect Circle", "judith"),
    ("Hoppípolla (2025 Remaster)", "Sigur Rós", "hoppipolla"),
    ("06. 3 Libras - A Perfect Circle", "A Perfect Circle", "3libras"),
    ("Song feat. Somebody", None, "song"),
])
def test_normalize_title(title, artist, expected):
    assert songMatch.normalize_title(title, artist) == expected


@pytest.mark.parametrize("channel, artist, expected", [
    ("A Perfect Circle - Topic", "A Perfect Circle", True),
    ("Rammstein Official", "Rammstein", True),
    ("RammsteinVEVO", "Rammstein", True),
    ("Mariam Sowa", "A Perfect Circle", False),
    ("", "Rammstein", False),
])
def test_artist_matches(channel, artist, expected):
    assert songMatch.artist_matches(channel, artist) is expected


@pytest.mark.parametrize("title, expected", [
    ("Dreams - 2004 Remaster", "Dreams"),
    ("Stairway to Heaven - Remaster", "Stairway to Heaven"),
    ("Bohemian Rhapsody - Remastered 2011", "Bohemian Rhapsody"),
    ("Song - Live at Wembley", "Song"),
    ("Rammstein - Sonne", "Rammstein - Sonne"),
    ("Judith", "Judith"),
])
def test_strip_version_suffix(title, expected):
    assert songMatch.strip_version_suffix(title) == expected


def test_artist_credit_lists_match_any_artist():
    assert songMatch.artist_matches("Miley Cyrus - Topic", "Miley Cyrus, Someone Else")
    assert songMatch.artist_matches("Someone Else", "Miley Cyrus & Someone Else")
    assert not songMatch.artist_matches("Random Uploads", "Miley Cyrus, Someone Else")
    assert songMatch.normalize_title("Dreams - 2004 Remaster", "Fleetwood Mac") == songMatch.normalize_title("Dreams", "Fleetwood Mac")


def test_clean_song_title():
    assert songMatch.clean_song_title("A Perfect Circle - Judith (Official Music Video)", "A Perfect Circle") == "Judith"
    assert songMatch.clean_song_title("The Hollow", "A Perfect Circle") == "The Hollow"
    assert songMatch.clean_song_title("Mein Herz brennt [Official 4K Video]", "Rammstein") == "Mein Herz brennt"


def test_keyword_flags_and_exemption():
    assert "live" in suggestFlags.compute_flags("Judith (Live at Red Rocks)")
    assert "live" not in suggestFlags.compute_flags("Judith (Live at Red Rocks)", requested_title="Judith - Live")
    flags = suggestFlags.compute_flags("Song (Lyrics) cover karaoke")
    assert {"lyrics", "cover", "karaoke"} <= set(flags)
    assert suggestFlags.compute_flags("Judith") == []


def test_duration_and_uploader_flags():
    assert "duration_mismatch" in suggestFlags.compute_flags("x", duration=300, spotify_duration=240)
    assert "duration_mismatch" not in suggestFlags.compute_flags("x", duration=243, spotify_duration=240)
    assert "too_long" in suggestFlags.compute_flags("x", duration=3600)
    assert "too_short" in suggestFlags.compute_flags("x", duration=30)
    assert "unofficial_uploader" in suggestFlags.compute_flags("x", channel="Fan Uploads", artist="Rammstein")
    assert "unofficial_uploader" not in suggestFlags.compute_flags("x", channel="Rammstein - Topic", artist="Rammstein")


def test_best_youtube_match_prefers_official_same_length():
    track = {"sp_title": "Judith", "sp_artist": "A Perfect Circle", "sp_duration_seconds": 246}
    candidates = [
        {"youtube_id": "a" * 11, "title": "A Perfect Circle - Judith (Live on Conan)", "channel": "alconcl", "duration": 249},
        {"youtube_id": "b" * 11, "title": "Judith (Lyrics)", "channel": "Lyric Channel", "duration": 246},
        {"youtube_id": "c" * 11, "title": "Judith", "channel": "A Perfect Circle - Topic", "duration": 245},
    ]
    assert lookupJobs.best_youtube_match(track, candidates)["youtube_id"] == "c" * 11
    assert lookupJobs.best_youtube_match(track, []) is None


def test_library_status():
    add_library_song("Judith", "A Perfect Circle", "Mer De Noms", youtube_id="Cp31A_iqoDw")
    suggestionsRepo.invalidate_library_index()
    assert suggestionsRepo.library_status({"youtube_id": "Cp31A_iqoDw", "title": "anything"}) == "yes"
    assert suggestionsRepo.library_status(
        {"youtube_id": "zzzzzzzzzzz", "title": "A Perfect Circle - Judith (Official Music Video)", "channel": "A Perfect Circle"}
    ) == "maybe"
    assert suggestionsRepo.library_status({"youtube_id": "zzzzzzzzzzz", "title": "Judith", "channel": "Someone Else"}) == "no"


def test_item_metadata_priority():
    item = {"title": "A Perfect Circle - Judith (Official Music Video)", "channel": "A Perfect Circle",
            "artist": None, "album": None, "track_number": None, "sp_title": None, "sp_artist": None, "sp_album": None}
    meta = approvedDownloads.item_metadata(item, {"upload_date": "20091003"})
    assert meta == {"artist": "A Perfect Circle", "album_artist": "A Perfect Circle", "album": "Singles",
                    "title": "Judith", "track_number": 0, "disc_number": 0, "year": "2009", "genre": None}

    item.update(sp_title="Judith", sp_artist="A Perfect Circle", sp_album="Mer de Noms")
    meta = approvedDownloads.item_metadata(item, {"album": "Wrong Album", "track_number": 7, "release_year": 1999})
    assert meta["album"] == "Mer de Noms"
    # Track/year belong to the release yt-dlp saw, not the Spotify album.
    assert meta["track_number"] == 0 and meta["year"] is None

    topic = {"title": "The Hollow", "channel": "A Perfect Circle - Topic", "artist": None, "album": None,
             "track_number": None, "sp_title": None, "sp_artist": None, "sp_album": None}
    info = {"artists": ["A Perfect Circle", "Someone Else"], "album": "Mer De Noms", "track": "The Hollow",
            "track_number": 1, "release_year": 2000, "album_artist": "A Perfect Circle", "genres": ["Rock"]}
    meta = approvedDownloads.item_metadata(topic, info)
    assert meta == {"artist": "A Perfect Circle", "album_artist": "A Perfect Circle", "album": "Mer De Noms",
                    "title": "The Hollow", "track_number": 1, "disc_number": 0, "year": "2000", "genre": "Rock"}



def test_playlist_position_is_not_a_track_number(monkeypatch):
    def entry(video_id, index, playlist_id):
        return {"id": video_id, "ie_key": "Youtube", "title": "Song", "playlist_index": index,
                "playlist_id": playlist_id, "playlist_title": "Album - Mer De Noms"}
    monkeypatch.setattr(musicSearch, "_run_flat_playlist_json", lambda *a, **k: [entry("aaaaaaaaaaa", 57, "PLmix")])
    assert musicSearch.list_playlist_tracks("x")[0]["track_number"] is None
    monkeypatch.setattr(musicSearch, "_run_flat_playlist_json", lambda *a, **k: [entry("aaaaaaaaaaa", 3, "OLAK5uyAlbum")])
    track = musicSearch.list_playlist_tracks("x")[0]
    assert track["track_number"] == 3 and track["album"] == "Mer De Noms"


def test_stored_playlist_position_is_ignored_on_download():
    item = {"title": "The Hollow", "channel": "A Perfect Circle - Topic", "artist": None, "album": None,
            "track_number": 57, "source": "yt_playlist", "sp_title": None, "sp_artist": None, "sp_album": None}
    info = {"album": "Mer De Noms", "track_number": 1}
    assert approvedDownloads.item_metadata(item, info)["track_number"] == 1
    assert approvedDownloads.item_metadata(dict(item, source="ytm_album"), info)["track_number"] == 57

@pytest.mark.parametrize("title, channel, expected", [
    ("Rammstein - Sonne (Official Video)", "Rammstein Official", "Rammstein"),
    ("Sonne", "RammsteinVEVO", "Rammstein"),
    ("The Hollow", "A Perfect Circle - Topic", "A Perfect Circle"),
    ("Some Band - Song", "Random Uploader", "Random Uploader"),
])
def test_artist_from_upload(title, channel, expected):
    assert songMatch.artist_from_upload(title, channel) == expected


def test_uploader_tag_is_not_trusted_as_artist():
    item = {"title": "Rammstein - Sonne (Official Video)", "channel": "Rammstein Official", "artist": None,
            "album": None, "track_number": None, "sp_title": None, "sp_artist": None, "sp_album": None}
    meta = approvedDownloads.item_metadata(item, {"artist": "Rammstein Official"})
    assert meta["artist"] == "Rammstein" and meta["title"] == "Sonne"


def test_target_path_is_sanitized():
    meta = {"artist": 'AC/DC', "album": 'What?: "Live"', "title": "Back In Black.", "track_number": 3}
    path = approvedDownloads.target_path("/lib", meta, ".flac")
    assert path == Path("/lib") / "Album - What__ _Live_" / "03 - Back In Black.flac"
    singles = dict(meta, album="Singles", track_number=0)
    assert approvedDownloads.target_path("/lib", singles, ".mp3") == Path("/lib") / "Singles" / "00 - Back In Black.mp3"
    assert approvedDownloads.safe_name("...", "fallback") == "fallback"


def test_track_number_in_album():
    meta = {"artist": "A Perfect Circle", "album": "Mer De Noms", "title": "The Hollow"}
    tracks = [
        {"youtube_id": "aaaaaaaaaaa", "title": "The Hollow", "album": "Mer de Noms", "track_number": 1},
        {"youtube_id": "bbbbbbbbbbb", "title": "Magdalena", "album": "Mer de Noms", "track_number": 2},
    ]
    assert approvedDownloads.track_number_in_album(tracks, meta, "bbbbbbbbbbb") == 2
    # A music video's ID isn't on the album, so the title decides.
    assert approvedDownloads.track_number_in_album(tracks, meta, "zzzzzzzzzzz") == 1
    assert approvedDownloads.track_number_in_album(tracks, dict(meta, album="Thirteenth Step"), "aaaaaaaaaaa") == 0
    assert approvedDownloads.track_number_in_album(tracks, dict(meta, title="Judith"), "zzzzzzzzzzz") == 0
    assert approvedDownloads.track_number_in_album([], meta, "aaaaaaaaaaa") == 0
