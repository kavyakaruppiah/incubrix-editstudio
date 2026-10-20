from app.engine.parse_cache import ParseCache


def test_parse_cache_key_changes_with_context_model_and_prompt_version():
    base = ParseCache.key("cut the intro", {"duration": 60}, "local:model")
    assert base == ParseCache.key(" cut the intro ", {"duration": 60}, "local:model")
    assert base != ParseCache.key("cut the intro", {"duration": 61}, "local:model")
    assert base != ParseCache.key("cut the intro", {"duration": 60}, "other:model")
    assert base != ParseCache.key("cut the intro", {"duration": 60}, "local:model", "prompt_v2")


def test_parse_cache_returns_copies_and_evicts_oldest_entry():
    cache = ParseCache(max_entries=1)
    cache.put("a", {"actions": [{"operation": "cut"}]})
    first = cache.get("a")
    first["actions"].clear()
    assert cache.get("a") == {"actions": [{"operation": "cut"}]}

    cache.put("b", {"actions": []})
    assert cache.get("a") is None
    assert cache.get("b") == {"actions": []}
