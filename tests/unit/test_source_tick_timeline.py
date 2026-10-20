from app.core.timeline import (
    EditOperation,
    SourceWord,
    Timeline,
    append_operation,
    canonical_hash,
    derive_timeline,
    out_to_src,
    redo,
    replay,
    restore,
    src_to_out,
    undo,
)


def test_cut_replay_and_source_mapping_use_integer_ticks():
    timeline = Timeline(900_000, (SourceWord("w_000001", 90_000, 180_000, "hello"),))
    timeline = append_operation(timeline, EditOperation("op_000001", "cut", start_tick=270_000, end_tick=450_000))

    assert [(s.start_tick, s.end_tick) for s in replay(timeline)] == [(0, 270_000), (450_000, 900_000)]
    assert src_to_out(timeline, 540_000) == (360_000,)
    assert out_to_src(timeline, 360_000) == (1, 540_000)


def test_speed_uses_ratio_and_later_operation_wins_overlap():
    timeline = Timeline(900_000)
    timeline = append_operation(timeline, EditOperation("op_000001", "speed", start_tick=0, end_tick=600_000, speed_num=2))
    timeline = append_operation(timeline, EditOperation("op_000002", "speed", start_tick=300_000, end_tick=900_000, speed_num=3))

    assert [(s.start_tick, s.end_tick, s.speed_num) for s in replay(timeline)] == [
        (0, 300_000, 2), (300_000, 600_000, 3), (600_000, 900_000, 3)
    ]


def test_keep_and_move_use_source_intervals_and_anchor_semantics():
    timeline = Timeline(900_000)
    timeline = append_operation(timeline, EditOperation("op_000001", "keep", start_tick=90_000, end_tick=810_000))
    timeline = append_operation(timeline, EditOperation("op_000002", "move", start_tick=450_000, end_tick=630_000, anchor_tick=90_000))

    assert [(s.start_tick, s.end_tick) for s in replay(timeline)] == [
        (450_000, 630_000), (90_000, 450_000), (630_000, 810_000)
    ]


def test_undo_redo_restore_and_new_edit_branch_are_deterministic():
    original = Timeline(900_000)
    edited = append_operation(original, EditOperation("op_000001", "cut", start_tick=0, end_tick=90_000))
    undone = undo(edited)
    assert replay(undone) == replay(original)
    assert redo(undone) == edited

    branched = append_operation(undone, EditOperation("op_000002", "cut", start_tick=90_000, end_tick=180_000))
    assert [op.state for op in branched.history] == ["disabled", "active"]
    assert [(s.start_tick, s.end_tick) for s in replay(branched)] == [(0, 90_000), (180_000, 900_000)]
    assert replay(restore(branched, "op_000002")) == replay(original)
    assert canonical_hash(branched) == canonical_hash(branched)


def test_hash_is_integer_only_and_excludes_no_timeline_content():
    timeline = Timeline(900_000, (SourceWord("w_000001", 1, 2, "x", confidence_milli=410),))
    assert set(canonical_hash(timeline)) == set("0123456789abcdef")
    assert isinstance(canonical_hash(timeline), str)


def test_caption_follows_surviving_words_and_returns_when_cut_is_restored():
    source = Timeline(900_000, (
        SourceWord("w_000001", 90_000, 180_000, "first"),
        SourceWord("w_000002", 270_000, 360_000, "second"),
    ))
    with_caption = append_operation(source, EditOperation(
        "op_000001", "caption", word_ids=("w_000001", "w_000002"), text="First second"
    ))
    cut = append_operation(with_caption, EditOperation(
        "op_000002", "cut", start_tick=0, end_tick=200_000
    ))
    derived = derive_timeline(cut)
    assert derived.captions[0].visible_word_ids == ("w_000002",)
    assert not derived.captions[0].hidden

    restored = restore(cut, "op_000002")
    assert derive_timeline(restored).captions[0].visible_word_ids == ("w_000001", "w_000002")

    hidden = append_operation(with_caption, EditOperation(
        "op_000003", "cut", start_tick=0, end_tick=900_000
    ))
    assert derive_timeline(hidden).captions[0].hidden
    assert derive_timeline(hidden).captions[0].warnings


def test_mute_and_bleep_ranges_are_clipped_to_surviving_source_content():
    timeline = Timeline(900_000)
    timeline = append_operation(timeline, EditOperation("op_000001", "cut", start_tick=270_000, end_tick=450_000))
    timeline = append_operation(timeline, EditOperation("op_000002", "mute", start_tick=180_000, end_tick=540_000))
    timeline = append_operation(timeline, EditOperation("op_000003", "bleep", start_tick=180_000, end_tick=540_000))

    derived = derive_timeline(timeline)
    assert derived.audio_effects[0].source_intervals == ((180_000, 270_000), (450_000, 540_000))
    assert derived.audio_effects[1].source_intervals == ((180_000, 270_000), (450_000, 540_000))
