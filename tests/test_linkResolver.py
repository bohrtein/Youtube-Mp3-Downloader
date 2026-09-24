import pytest

from core.linkResolver import LinkError, extract_video_id, is_video_id, parse_link


@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=Cp31A_iqoDw", "Cp31A_iqoDw"),
    ("https://music.youtube.com/watch?v=EJXUdPr4Naw&list=RDAMVM", "EJXUdPr4Naw"),
    ("https://youtu.be/xTgKRCXybSM?si=abc", "xTgKRCXybSM"),
    ("https://www.youtube.com/shorts/xTgKRCXybSM", "xTgKRCXybSM"),
    ("https://www.instagram.com/aperfectcircle", None),
    ("https://evil.com/watch?v=Cp31A_iqoDw", None),
    ("https://www.youtube.com/watch?v=Cp31A_iqoDwX", None),
    (None, None),
])
def test_extract_video_id(url, expected):
    assert extract_video_id(url) == expected


@pytest.mark.parametrize("raw, kind, canonical", [
    ("https://www.youtube.com/watch?v=Cp31A_iqoDw&t=30", "video", "https://www.youtube.com/watch?v=Cp31A_iqoDw"),
    ("youtu.be/Cp31A_iqoDw", "video", "https://www.youtube.com/watch?v=Cp31A_iqoDw"),
    ("https://music.youtube.com/watch?v=EJXUdPr4Naw&list=OLAK5uy_x", "video", "https://www.youtube.com/watch?v=EJXUdPr4Naw"),
    ("https://www.youtube.com/playlist?list=PLabcdefghij123", "playlist", "https://www.youtube.com/playlist?list=PLabcdefghij123"),
    ("https://music.youtube.com/playlist?list=OLAK5uy_lDjR8c6Pm_y5F3zNW0Nj3bRi08tpfzXRQ", "playlist",
     "https://www.youtube.com/playlist?list=OLAK5uy_lDjR8c6Pm_y5F3zNW0Nj3bRi08tpfzXRQ"),
    ("https://music.youtube.com/browse/MPREb_MWhf2IcLITS", "album", "https://music.youtube.com/browse/MPREb_MWhf2IcLITS"),
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x", "spotify_playlist",
     "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
    ("https://open.spotify.com/intl-de/album/4LH4d3cOWNNsVw41Gqt2kv", "spotify_album",
     "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv"),
    ("https://open.spotify.com/track/7ouMYWpwJ422jRcDASZB7P", "spotify_track",
     "https://open.spotify.com/track/7ouMYWpwJ422jRcDASZB7P"),
])
def test_parse_link_rebuilds_canonical_urls(raw, kind, canonical):
    link = parse_link(raw)
    assert link["kind"] == kind
    assert link["url"] == canonical


@pytest.mark.parametrize("raw", [
    "",
    "--exec=calc",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://evil.com/watch?v=Cp31A_iqoDw",
    "https://youtube.com.evil.com/watch?v=Cp31A_iqoDw",
    "https://www.youtube.com/channel/UC0UUsQjUpLtlG6dF60DQeIQ",
    "https://www.youtube.com/playlist?list=--exec",
    "https://open.spotify.com/artist/0LcJLqbBmaGUft1e9Mm8HV",
    "https://www.youtube.com/watch?v=" + "a" * 400,
])
def test_parse_link_rejects(raw):
    with pytest.raises(LinkError):
        parse_link(raw)


@pytest.mark.parametrize("value, expected", [
    ("Cp31A_iqoDw", True),
    ("Cp31A_iqoD", False),
    ("-exec=calc1", False),
    ("../../etc/p", False),
    ("", False),
    (None, False),
])
def test_is_video_id(value, expected):
    assert is_video_id(value) is expected
