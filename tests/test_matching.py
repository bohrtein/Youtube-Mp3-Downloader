from pathlib import Path

import pytest

import core.approvedDownloads as approvedDownloads
import core.lookupJobs as lookupJobs
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
    meta = approvedDownloads.item_metadata(item, {})
    assert meta == {"artist": "A Perfect Circle", "album": "Singles", "title": "Judith", "track_number": 0}

    item.update(sp_title="Judith", sp_artist="A Perfect Circle", sp_album="Mer de Noms")
    meta = approvedDownloads.item_metadata(item, {"album": ["Wrong Album"]})
    assert meta["album"] == "Mer de Noms"

    topic = {"title": "The Hollow", "channel": "A Perfect Circle - Topic", "artist": None, "album": None,
             "track_number": 1, "sp_title": None, "sp_artist": None, "sp_album": None}
    meta = approvedDownloads.item_metadata(topic, {"artist": ["A Perfect Circle"], "album": ["Mer De Noms"]})
    assert meta == {"artist": "A Perfect Circle", "album": "Mer De Noms", "title": "The Hollow", "track_number": 1}


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
    meta = approvedDownloads.item_metadata(item, {"artist": ["Rammstein Official"]})
    assert meta["artist"] == "Rammstein" and meta["title"] == "Sonne"


def test_target_path_is_sanitized():
    meta = {"artist": 'AC/DC', "album": 'What?: "Live"', "title": "Back In Black.", "track_number": 3}
    path = approvedDownloads.target_path("/lib", meta, ".flac")
    assert path == Path("/lib") / "AC_DC" / "What__ _Live_" / "03 - Back In Black.flac"
    assert approvedDownloads.safe_name("...", "fallback") == "fallback"
