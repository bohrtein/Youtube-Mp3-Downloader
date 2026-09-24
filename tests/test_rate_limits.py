import time

import database.suggestionsRepo as suggestionsRepo


def test_try_consume_enforces_each_window(friend):
    limits = [(3600, 3), (86400, 5)]
    fid = friend["friend_id"]
    assert [suggestionsRepo.try_consume(fid, "search", limits) for _ in range(3)] == [0, 0, 0]
    retry = suggestionsRepo.try_consume(fid, "search", limits)
    assert 0 < retry <= 3601


def test_limits_are_per_friend_and_per_kind(friend):
    other = suggestionsRepo.create_friend("Other")
    limits = [(3600, 1)]
    assert suggestionsRepo.try_consume(friend["friend_id"], "search", limits) == 0
    assert suggestionsRepo.try_consume(friend["friend_id"], "search", limits) > 0
    assert suggestionsRepo.try_consume(other["friend_id"], "search", limits) == 0
    assert suggestionsRepo.try_consume(friend["friend_id"], "resolve", limits) == 0


def test_server_budget_uses_null_friend_and_cost():
    limits = [(86400, 5)]
    assert suggestionsRepo.try_consume(None, "ytdlp", limits, cost=3) == 0
    assert suggestionsRepo.try_consume(None, "ytdlp", limits, cost=3) > 0
    assert suggestionsRepo.try_consume(None, "ytdlp", limits, cost=2) == 0


def test_old_events_expire(friend, monkeypatch):
    limits = [(60, 1)]
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() - 120)
    assert suggestionsRepo.try_consume(friend["friend_id"], "submit", limits) == 0
    monkeypatch.setattr(time, "time", real_time)
    assert suggestionsRepo.try_consume(friend["friend_id"], "submit", limits) == 0


def test_cache_ttl():
    suggestionsRepo.cache_set("k", {"results": [1]})
    assert suggestionsRepo.cache_get("k", 60) == {"results": [1]}
    assert suggestionsRepo.cache_get("k", -1) is None
    assert suggestionsRepo.cache_get("missing", 60) is None
