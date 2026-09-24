import re
import pytest

import core.lookupJobs as lookupJobs
import database.suggestionsRepo as suggestionsRepo
import routes.friendsPublic as friendsPublic
from tests.conftest import ADMIN_HEADERS


def song(youtube_id, title="Judith", channel="A Perfect Circle", duration=246, **extra):
    return dict(youtube_id=youtube_id, title=title, channel=channel, duration=duration, source="search", **extra)


def serve(friend, *songs):
    """Pretend these songs were shown to the friend by a search."""
    lookupJobs._remember_served(friend["friend_id"], list(songs))


# --- access control --------------------------------------------------------------

@pytest.mark.parametrize("method, path", [
    ("get", "/"), ("get", "/library"), ("get", "/album/1"), ("get", "/browse_folders"),
    ("post", "/set_library_folder"), ("delete", "/delete_album/1"), ("delete", "/delete_song/1"),
    ("get", "/friends"), ("post", "/friends"), ("get", "/review"), ("get", "/review/1"),
    ("post", "/review/1/approve"), ("post", "/settings/suggestions"),
])
def test_admin_routes_404_without_hub_secret(client, method, path):
    assert getattr(client, method)(path).status_code == 404
    assert getattr(client, method)(path, headers={"X-Apphub-Auth": "wrong"}).status_code == 404


def test_admin_pages_work_with_hub_secret(client):
    for path in ("/", "/library", "/friends", "/review"):
        assert client.get(path, headers=ADMIN_HEADERS).status_code == 200, path


def test_public_routes_need_no_secret(client, friend):
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/suggest.css").status_code == 200
    assert client.get(f"/suggest/{friend['token']}/").status_code == 200
    assert client.get(f"/suggest/{friend['token']}/library").status_code == 200


def test_unknown_and_revoked_tokens_404(client, friend):
    assert client.get("/suggest/not-a-real-token-at-all-xx/").status_code == 404
    assert client.get("/suggest/short/").status_code == 404
    suggestionsRepo.revoke_friend(friend["friend_id"])
    assert client.get(f"/suggest/{friend['token']}/").status_code == 404


def test_rotated_token_replaces_old_one(client, friend):
    new_token = suggestionsRepo.rotate_friend_token(friend["friend_id"])
    assert client.get(f"/suggest/{friend['token']}/").status_code == 404
    assert client.get(f"/suggest/{new_token}/").status_code == 200


def test_friend_pages_send_security_headers(client, friend):
    response = client.get(f"/suggest/{friend['token']}/")
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert b"<script>" not in response.data  # CSP forbids inline scripts


def test_friend_library_hides_paths_and_ids(client, friend):
    from tests.helpers import add_library_song
    add_library_song("Judith", "A Perfect Circle", "Mer De Noms", youtube_id="Cp31A_iqoDw")
    body = client.get(f"/suggest/{friend['token']}/library").data.decode()
    assert "Judith" in body
    assert "Cp31A_iqoDw" not in body and "youtube.com/watch" not in body
    assert "delete" not in body.lower()


def test_paused_suggestions(client, friend):
    suggestionsRepo.set_suggestions_enabled(False)
    assert client.get(f"/suggest/{friend['token']}/").status_code == 503
    response = client.post(f"/suggest/{friend['token']}/api/search", json={"mode": "song", "q": "x"})
    assert response.status_code == 503 and "paused" in response.get_json()["error"]


# --- lookups -----------------------------------------------------------------------

def test_search_serves_cache_without_charging(client, friend):
    suggestionsRepo.cache_set(lookupJobs.search_cache_key("song", "judith"), {"results": [song("Cp31A_iqoDw")], "note": None})
    for _ in range(40):  # well past the 30/hour limit: cache hits are free
        response = client.post(f"/suggest/{friend['token']}/api/search", json={"mode": "song", "q": "  Judith "})
        assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "done" and data["results"][0]["in_library"] == "no"
    assert lookupJobs.served_song(friend["friend_id"], "Cp31A_iqoDw")["title"] == "Judith"


@pytest.mark.parametrize("payload", [
    {"mode": "video", "q": "x"}, {"mode": "song", "q": ""}, {"mode": "song", "q": "x" * 101},
])
def test_search_input_validation(client, friend, payload):
    assert client.post(f"/suggest/{friend['token']}/api/search", json=payload).status_code == 400


def test_resolve_rejects_foreign_links(client, friend):
    response = client.post(f"/suggest/{friend['token']}/api/resolve", json={"url": "https://evil.com/x"})
    assert response.status_code == 400


def test_api_requires_json(client, friend):
    assert client.post(f"/suggest/{friend['token']}/api/search", data="mode=song&q=x").status_code == 415


def test_jobs_are_private_to_their_friend(client, friend):
    other = suggestionsRepo.create_friend("Other")
    lookupJobs._jobs["job1"] = {"friend_id": other["friend_id"], "status": "done", "results": [], "note": None,
                                "error": None, "progress": None, "created": 9e18}
    try:
        assert client.get(f"/suggest/{friend['token']}/api/jobs/job1").status_code == 404
        assert client.get(f"/suggest/{other['token']}/api/jobs/job1").status_code == 200
    finally:
        del lookupJobs._jobs["job1"]


# --- submissions -------------------------------------------------------------------

def submit(client, friend, items, message=None):
    return client.post(f"/suggest/{friend['token']}/api/submit", json={"items": items, "message": message})


def test_submit_keeps_kept_and_unticked_with_server_metadata(client, friend):
    serve(friend, song("Cp31A_iqoDw"), song("xTgKRCXybSM", title="3 Libras (Live)"))
    response = submit(client, friend, [
        {"youtube_id": "Cp31A_iqoDw", "kept": True, "title": "FAKE TITLE"},
        {"youtube_id": "xTgKRCXybSM", "kept": False},
    ], message="for the road trip")
    assert response.status_code == 201
    submission = suggestionsRepo.get_submission(response.get_json()["submission_id"])
    assert submission["message"] == "for the road trip"
    kept = [i for i in submission["items"] if i["kept"]]
    unticked = [i for i in submission["items"] if not i["kept"]]
    assert [i["title"] for i in kept] == ["Judith"]  # never the page's title
    assert [i["youtube_id"] for i in unticked] == ["xTgKRCXybSM"]
    assert "live" in unticked[0]["flags"]


def test_submit_rejects_songs_never_served(client, friend):
    serve(friend, song("Cp31A_iqoDw"))
    response = submit(client, friend, [{"youtube_id": "Cp31A_iqoDw", "kept": True},
                                        {"youtube_id": "zzzzzzzzzzz", "kept": True}])
    assert response.status_code == 409
    assert response.get_json()["expired"] == ["zzzzzzzzzzz"]


def test_submit_songs_served_to_another_friend_are_rejected(client, friend):
    other = suggestionsRepo.create_friend("Other")
    serve(other, song("Cp31A_iqoDw"))
    assert submit(client, friend, [{"youtube_id": "Cp31A_iqoDw", "kept": True}]).status_code == 409


@pytest.mark.parametrize("items", [
    [], "nope", [{"youtube_id": "../etc/passwd", "kept": True}], [{"youtube_id": "Cp31A_iqoDw", "kept": False}],
])
def test_submit_validation(client, friend, items):
    serve(friend, song("Cp31A_iqoDw"))
    assert submit(client, friend, items).status_code == 400


def test_submit_limits(client, friend):
    ids = [f"id{n:09d}" for n in range(friendsPublic.MAX_KEPT_ITEMS + 1)]
    serve(friend, *[song(i) for i in ids])
    assert submit(client, friend, [{"youtube_id": i, "kept": True} for i in ids]).status_code == 400
    for n in range(3):
        assert submit(client, friend, [{"youtube_id": ids[n], "kept": True}]).status_code == 201
    response = submit(client, friend, [{"youtube_id": ids[3], "kept": True}])
    assert response.status_code == 429  # 3 waiting for review already


def test_friend_sees_only_own_submission_summaries(client, friend):
    serve(friend, song("Cp31A_iqoDw"))
    submit(client, friend, [{"youtube_id": "Cp31A_iqoDw", "kept": True}])
    subs = client.get(f"/suggest/{friend['token']}/api/submissions").get_json()["submissions"]
    assert len(subs) == 1 and subs[0]["kept_count"] == 1
    assert set(subs[0]) == {"submission_id", "status", "created_at", "kept_count", "downloaded_count"}


# --- admin review -------------------------------------------------------------------

def make_submission(client, friend):
    serve(friend, song("Cp31A_iqoDw"), song("xTgKRCXybSM", title="Passive"), song("kBUd9xs8JaM", title="Magdalena"))
    response = submit(client, friend, [
        {"youtube_id": "Cp31A_iqoDw", "kept": True},
        {"youtube_id": "xTgKRCXybSM", "kept": True},
        {"youtube_id": "kBUd9xs8JaM", "kept": False},
    ])
    return response.get_json()["submission_id"]


def test_review_pages_render(client, friend):
    submission_id = make_submission(client, friend)
    page = client.get(f"/review/{submission_id}", headers=ADMIN_HEADERS)
    assert page.status_code == 200
    html = page.data.decode()
    assert "Judith" in html and "Magdalena" in html and "unticked by Test Friend" in html
    assert "Test Friend" in client.get("/review", headers=ADMIN_HEADERS).data.decode()


def test_friend_text_is_escaped_on_review_page(client):
    evil = suggestionsRepo.create_friend("<script>alert(1)</script>")
    serve(evil, song("Cp31A_iqoDw", title="<img src=x onerror=alert(1)>"))
    submission_id = submit(client, evil, [{"youtube_id": "Cp31A_iqoDw", "kept": True}],
                           message="<b>hi</b>").get_json()["submission_id"]
    html = client.get(f"/review/{submission_id}", headers=ADMIN_HEADERS).data.decode()
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html and "<b>hi</b>" not in html


def test_approve_marks_selected_downloading_and_rest_skipped(client, friend, monkeypatch):
    import core.approvedDownloads as approvedDownloads
    calls = []
    monkeypatch.setattr(approvedDownloads, "run_approval", lambda *args: calls.append(args))
    submission_id = make_submission(client, friend)
    items = suggestionsRepo.get_submission(submission_id)["items"]
    first = items[0]["item_id"]

    assert client.post(f"/review/{submission_id}/approve", json={"item_ids": []}, headers=ADMIN_HEADERS).status_code == 400
    response = client.post(f"/review/{submission_id}/approve", json={"item_ids": [first], "format": "mp3"}, headers=ADMIN_HEADERS)
    assert response.status_code == 202
    decisions = {i["item_id"]: i["decision"] for i in suggestionsRepo.get_submission(submission_id)["items"]}
    assert decisions[first] == "downloading"
    assert sorted(d for k, d in decisions.items() if k != first) == ["skipped", "skipped"]
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls and calls[0][1] == [first] and calls[0][2] == "mp3"


def test_approve_allows_redownloading_a_downloaded_song(client, friend, monkeypatch):
    import core.approvedDownloads as approvedDownloads
    calls = []
    monkeypatch.setattr(approvedDownloads, "run_approval", lambda *args: calls.append(args))
    submission_id = make_submission(client, friend)
    items = suggestionsRepo.get_submission(submission_id)["items"]
    first, second = items[0]["item_id"], items[1]["item_id"]
    suggestionsRepo.set_item_decision(first, "downloaded")
    suggestionsRepo.set_submission_status(submission_id, "done")

    page = client.get(f"/review/{submission_id}", headers=ADMIN_HEADERS).data.decode()
    checkbox = re.search(rf'<input class="sg-check"[^>]*value="{first}"[^>]*>', page).group(0)
    assert "disabled" not in checkbox and "checked" not in checkbox
    response = client.post(f"/review/{submission_id}/approve", json={"item_ids": [first, second]}, headers=ADMIN_HEADERS)
    assert response.status_code == 202
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls and sorted(calls[0][1]) == sorted([first, second]) and calls[0][4] == {first}


def test_admin_posts_require_json(client, friend):
    submission_id = make_submission(client, friend)
    response = client.post(f"/review/{submission_id}/reject", data="x", headers=ADMIN_HEADERS)
    assert response.status_code == 415


def test_reject(client, friend):
    submission_id = make_submission(client, friend)
    assert client.post(f"/review/{submission_id}/reject", json={}, headers=ADMIN_HEADERS).status_code == 200
    submission = suggestionsRepo.get_submission(submission_id)
    assert submission["status"] == "rejected"
    assert {i["decision"] for i in submission["items"]} == {"skipped"}


def test_fix_match(client, friend, monkeypatch):
    import core.musicSearch as musicSearch
    monkeypatch.setattr(musicSearch, "get_video", lambda vid: {
        "youtube_id": vid, "title": "Judith (Live)", "channel": "Someone", "duration": 900,
        "artist": None, "album": None, "track_number": None,
    })
    submission_id = make_submission(client, friend)
    item_id = suggestionsRepo.get_submission(submission_id)["items"][0]["item_id"]
    assert client.post(f"/review/items/{item_id}/match", json={"video": "not a video"}, headers=ADMIN_HEADERS).status_code == 400
    response = client.post(f"/review/items/{item_id}/match", json={"video": "https://youtu.be/AAAAAAAAAAA"}, headers=ADMIN_HEADERS)
    assert response.status_code == 200
    item = suggestionsRepo.get_item(item_id)
    assert item["youtube_id"] == "AAAAAAAAAAA" and item["orig_youtube_id"] == "Cp31A_iqoDw"
    assert "live" in item["flags"]


def test_friend_admin_endpoints(client):
    response = client.post("/friends", json={"name": "Sam"}, headers=ADMIN_HEADERS)
    assert response.status_code == 201
    assert "/suggest/" in response.get_json()["link"]
    assert client.post("/friends", json={"name": "  "}, headers=ADMIN_HEADERS).status_code == 400
    assert client.post("/settings/suggestions", json={"public_base_url": "ftp://x"}, headers=ADMIN_HEADERS).status_code == 400
    assert client.post("/settings/suggestions", json={"public_base_url": "https://box.ts.net:8443/"},
                       headers=ADMIN_HEADERS).status_code == 200
    friend_id = response.get_json()["friend_id"]
    link = client.post(f"/friends/{friend_id}/rotate", json={}, headers=ADMIN_HEADERS).get_json()["link"]
    assert link.startswith("https://box.ts.net:8443/suggest/")
