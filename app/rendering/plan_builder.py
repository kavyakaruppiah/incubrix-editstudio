import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from app.config import settings
from app.engine.time_policy import resolve_anchor_words_to_output_range
from app.models.timeline import CaptionStyle, Timeline, TimelineCaption


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS subtitle timestamp: H:MM:SS.cs"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def has_tamil_text(text: str) -> bool:
    """Check if string contains Tamil Unicode block characters (U+0B80 - U+0BFF)."""
    return bool(re.search(r"[\u0B80-\u0BFF]", text))


def generate_ass_subtitles(timeline: Timeline, output_ass_path: Path) -> bool:
    """
    Generate an Advanced SubStation Alpha (.ass) subtitle file from anchored timeline captions.
    Supports:
    - Typography controls: font family, font size, bold, italic, colors, outline, shadow, background box
    - Unicode shaping: Automatic font fallback to Nirmala UI or Noto Sans Tamil for Tamil text
    - Modes: standard sentence, word-by-word reveal, karaoke active-word highlight, speaker labels
    Returns True if at least one caption event was written.
    """
    captions = timeline.captions
    if not captions:
        return False

    global_style = getattr(timeline, "global_caption_style", CaptionStyle())
    cap_mode = getattr(timeline, "caption_mode", "sentence")

    # Detect if any caption has Tamil script
    contains_tamil = any(has_tamil_text(c.text) for c in captions)
    font_name = global_style.font_name
    if contains_tamil and font_name.lower() in ("arial", "sans-serif", "helvetica", "dejavu sans"):
        font_name = "Nirmala UI"

    font_size = global_style.font_size
    primary_color = global_style.primary_color
    outline_color = global_style.outline_color
    back_color = global_style.back_color
    bold_val = -1 if global_style.bold else 0
    italic_val = -1 if global_style.italic else 0
    outline_w = global_style.outline_width
    shadow_w = global_style.shadow_offset
    border_style = global_style.border_style
    margin_v = global_style.margin_v
    align_bottom = global_style.alignment or 2
    karaoke_col = global_style.karaoke_color or "&H0000FFFF"

    header = f"""[Script Info]
Title: Timeline Generated Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_color},{bold_val},{italic_val},0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},{align_bottom},30,30,{margin_v},1
Style: Top,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_color},{bold_val},{italic_val},0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},8,30,30,40,1
Style: Center,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},{back_color},{bold_val},{italic_val},0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},5,30,30,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: List[str] = []

    for cap in captions:
        # Resolve anchor words to current output timing
        anchor_words = [timeline.transcript.get_word_by_id(wid) for wid in cap.anchor_word_ids]
        valid_words = [w for w in anchor_words if w]
        if not valid_words:
            continue

        out_start, out_end, status = resolve_anchor_words_to_output_range(timeline.segments, valid_words)
        if status != "anchored" or out_start is None or out_end is None:
            # Word is cut from current timeline
            continue

        style_name = "Default"
        if cap.style.position == "top":
            style_name = "Top"
        elif cap.style.position == "center":
            style_name = "Center"
        effective_mode = cap_mode if (cap_mode and cap_mode != "sentence") else getattr(cap.style, "mode", "sentence")
        if getattr(cap.style, "mode", None) and cap.style.mode != "sentence":
            effective_mode = cap.style.mode

        if effective_mode == "word_by_word":
            # Display one word at a time at its exact output window
            for w in valid_words:
                w_start, w_end, w_status = resolve_anchor_words_to_output_range(timeline.segments, [w])
                if w_status == "anchored" and w_start is not None and w_end is not None:
                    s_str = format_ass_time(w_start)
                    e_str = format_ass_time(w_end)
                    clean_w = w.text.replace("\n", " ").strip()
                    events.append(f"Dialogue: 0,{s_str},{e_str},{style_name},,0,0,0,,{clean_w}")

        elif effective_mode == "karaoke":
            # Display entire phrase with active word highlighted in karaoke_color as spoken
            for idx, active_w in enumerate(valid_words):
                w_start, w_end, w_status = resolve_anchor_words_to_output_range(timeline.segments, [active_w])
                if w_status != "anchored" or w_start is None or w_end is None:
                    continue
                s_str = format_ass_time(w_start)
                e_str = format_ass_time(w_end)

                # Build line with active word highlighted
                parts = []
                for j, w in enumerate(valid_words):
                    clean_token = w.text.replace("\n", " ").strip()
                    if j == idx:
                        parts.append(f"{{\\c{karaoke_col}&}}{clean_token}{{\\c{primary_color}&}}")
                    else:
                        parts.append(clean_token)
                highlighted_line = " ".join(parts)
                events.append(f"Dialogue: 0,{s_str},{e_str},{style_name},,0,0,0,,{highlighted_line}")

        else:
            # Standard sentence or speaker_labelled mode
            # Keep accelerated speech captions readable when the source word
            # interval collapses, but never extend past the rendered timeline.
            minimum_caption_s = 0.7
            if out_end - out_start < minimum_caption_s:
                out_end = min(timeline.total_output_duration, out_start + minimum_caption_s)
            start_str = format_ass_time(out_start)
            end_str = format_ass_time(out_end)
            prefix = ""
            if effective_mode == "speaker_labelled" and valid_words[0].speaker:
                prefix = f"[{valid_words[0].speaker}] "
            clean_text = prefix + cap.text.replace("\n", "\\N")
            events.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{clean_text}")

    if not events:
        return False

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events) + "\n")

    return True


def build_atempo_filter(speed: float) -> str:
    """
    Build atempo filter chain for audio speed changes.
    FFmpeg's atempo filter only supports values between 0.5 and 2.0 per instance.
    """
    filters = []
    current = speed
    while current > 2.0:
        filters.append("atempo=2.0")
        current /= 2.0
    while current < 0.5:
        filters.append("atempo=0.5")
        current /= 0.5
    filters.append(f"atempo={current:.4f}")
    return ",".join(filters)


class RenderPlan:
    def __init__(self, command: List[str], temp_files: List[Path]):
        self.command = command
        self.temp_files = temp_files


def escape_ffmpeg_filter_path(path_str: str) -> str:
    """Escape windows file paths for FFmpeg filter argument syntax."""
    clean = path_str.replace("\\", "/")
    clean = clean.replace(":", r"\:")
    clean = clean.replace("'", r"\'")
    return clean


def build_render_plan(
    timeline: Timeline,
    media_source_path: str,
    output_path: str,
    temp_dir: str | Path,
    quality: Optional[int] = None,
    preset: Optional[str] = None,
    frame_rate: int = 30,
) -> RenderPlan:
    """
    Build a complete, safe, deterministic FFmpeg execution plan from validated Timeline.
    Compiles:
    - Slices, speeds, concats
    - Aspect ratios (16:9, 9:16 vertical reel, 1:1)
    - Visual effects: brightness, contrast, saturation, gamma, blur, sharpen, color grading
    - Transitions: smooth fade-in and fade-out
    - Advanced ASS subtitles (Unicode/Tamil support, karaoke highlighting, word-by-word)
    - Audio tools: mute, bleep tones, ducking, normalization (loudnorm), fades
    """
    temp_files: List[Path] = []
    t_dir = Path(temp_dir)
    t_dir.mkdir(parents=True, exist_ok=True)

    has_audio = timeline.source_metadata.audio_present
    segments = timeline.segments
    filter_complex_parts: List[str] = []
    total_dur = timeline.total_output_duration
    ve = getattr(timeline, "video_effects", None)

    # 1. Trims and speeds for each segment
    v_out_tags: List[str] = []
    a_out_tags: List[str] = []

    for i, seg in enumerate(segments):
        v_tag_raw = f"v{i}_raw"
        v_tag_out = f"v{i}"
        filter_complex_parts.append(
            f"[0:v]trim=start={seg.source_start:.4f}:end={seg.source_end:.4f},setpts=PTS-STARTPTS[{v_tag_raw}]"
        )
        if abs(seg.speed - 1.0) > 1e-4:
            pts_factor = 1.0 / seg.speed
            filter_complex_parts.append(f"[{v_tag_raw}]setpts={pts_factor:.4f}*PTS[{v_tag_out}]")
        else:
            filter_complex_parts.append(f"[{v_tag_raw}]setpts=PTS[{v_tag_out}]")
        v_tag_normalized = f"v{i}_norm"
        filter_complex_parts.append(
            f"[{v_tag_out}]fps={frame_rate},settb=AVTB,format=yuv420p[{v_tag_normalized}]"
        )
        v_out_tags.append(v_tag_normalized)

        if has_audio:
            a_tag_raw = f"a{i}_raw"
            a_tag_out = f"a{i}"
            if seg.audio_enabled:
                filter_complex_parts.append(
                    f"[0:a]atrim=start={seg.source_start:.4f}:end={seg.source_end:.4f},asetpts=PTS-STARTPTS[{a_tag_raw}]"
                )
                if abs(seg.speed - 1.0) > 1e-4:
                    atempo_str = build_atempo_filter(seg.speed)
                    filter_complex_parts.append(f"[{a_tag_raw}]{atempo_str}[{a_tag_out}]")
                else:
                    filter_complex_parts.append(f"[{a_tag_raw}]asetpts=PTS[{a_tag_out}]")
            else:
                filter_complex_parts.append(
                    f"anullsrc=r={settings.RENDER_AUDIO_SAMPLE_RATE}:cl=stereo,"
                    f"atrim=duration={seg.output_duration:.4f},asetpts=PTS-STARTPTS[{a_tag_out}]"
                )
            a_out_tags.append(a_tag_out)

    # 2. Join segments with cuts or true overlapping video/audio transitions.
    n_segs = len(segments)
    last_v = v_out_tags[0]
    assembled_duration = segments[0].output_duration
    last_a = a_out_tags[0] if has_audio and a_out_tags else None
    for i in range(1, n_segs):
        seg = segments[i]
        next_v = v_out_tags[i]
        joined_v = f"v_join_{i}"
        transition_duration = seg.transition_duration
        if transition_duration > 0:
            if seg.transition_in == "dissolve":
                transition_name = "dissolve"
            elif seg.transition_in in ("wipe", "wipeleft"):
                transition_name = "wipeleft"
            else:
                transition_name = "fade"
            offset = max(0.0, assembled_duration - transition_duration)
            filter_complex_parts.append(
                f"[{last_v}][{next_v}]xfade=transition={transition_name}:"
                f"duration={transition_duration:.4f}:offset={offset:.4f}[{joined_v}]"
            )
            assembled_duration += seg.output_duration - transition_duration
        else:
            filter_complex_parts.append(f"[{last_v}][{next_v}]concat=n=2:v=1:a=0[{joined_v}]")
            assembled_duration += seg.output_duration
        last_v = joined_v

        if last_a is not None:
            joined_a = f"a_join_{i}"
            if transition_duration > 0:
                filter_complex_parts.append(
                    f"[{last_a}][{a_out_tags[i]}]acrossfade=d={transition_duration:.4f}:c1=tri:c2=tri[{joined_a}]"
                )
            else:
                filter_complex_parts.append(f"[{last_a}][{a_out_tags[i]}]concat=n=2:v=0:a=1[{joined_a}]")
            last_a = joined_a

    # Audio cuts/transitions are joined in lockstep with the video timeline.

    # Apply clip orientation and mirror transforms before fitting the output canvas.
    if ve:
        transform_filters: List[str] = []
        rotation = int(ve.rotation_degrees) % 360
        if rotation == 90:
            transform_filters.append("transpose=clock")
        elif rotation == 180:
            transform_filters.extend(["hflip", "vflip"])
        elif rotation == 270:
            transform_filters.append("transpose=cclock")
        if ve.horizontal_flip:
            transform_filters.append("hflip")
        if ve.vertical_flip:
            transform_filters.append("vflip")
        if transform_filters:
            transform_tag = "v_transformed"
            filter_complex_parts.append(f"[{last_v}]{','.join(transform_filters)}[{transform_tag}]")
            last_v = transform_tag

    # 3. Aspect Ratio Conversion
    target_ar = None
    if getattr(timeline, "aspect_ratio", None) and timeline.aspect_ratio != "original":
        target_ar = timeline.aspect_ratio
    elif ve and ve.aspect_ratio and ve.aspect_ratio != "original":
        target_ar = ve.aspect_ratio

    if target_ar:
        ar = target_ar.lower().strip()
        if ar in ("9:16", "vertical"):
            # Vertical reel format 1080x1920
            v_ar_tag = "v_aspect_9_16"
            filter_complex_parts.append(
                f"[{last_v}]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black[{v_ar_tag}]"
            )
            last_v = v_ar_tag
        elif ar in ("4:5", "portrait"):
            # Portrait social format 1080x1350
            v_ar_tag = "v_aspect_4_5"
            filter_complex_parts.append(
                f"[{last_v}]scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:black[{v_ar_tag}]"
            )
            last_v = v_ar_tag
        elif ar in ("1:1", "square"):
            # Square format 1080x1080
            v_ar_tag = "v_aspect_1_1"
            filter_complex_parts.append(
                f"[{last_v}]scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black[{v_ar_tag}]"
            )
            last_v = v_ar_tag
        elif ar in ("16:9", "landscape"):
            v_ar_tag = "v_aspect_16_9"
            filter_complex_parts.append(
                f"[{last_v}]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black[{v_ar_tag}]"
            )
            last_v = v_ar_tag

    # 4. Color Grading and Visual Adjustments
    if ve:
        v_effects_chain: List[str] = []

        # Color presets
        if ve.color_grade == "cinematic":
            v_effects_chain.append("eq=contrast=1.15:saturation=1.1:brightness=-0.02,colorbalance=rs=0.04:bs=-0.04:rm=0.04:bm=-0.04")
        elif ve.color_grade == "sepia":
            v_effects_chain.append("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131")
        elif ve.color_grade == "grayscale":
            v_effects_chain.append("hue=s=0")
        elif ve.color_grade == "warm":
            v_effects_chain.append("colorbalance=rs=0.08:gs=0.02:bs=-0.06")
        elif ve.color_grade == "cool":
            v_effects_chain.append("colorbalance=rs=-0.04:gs=0.0:bs=0.08")

        # Fine adjustments (brightness, contrast, saturation, gamma)
        if ve.brightness != 0.0 or ve.contrast != 1.0 or ve.saturation != 1.0 or ve.gamma != 1.0:
            v_effects_chain.append(
                f"eq=brightness={ve.brightness:.2f}:contrast={ve.contrast:.2f}:saturation={ve.saturation:.2f}:gamma={ve.gamma:.2f}"
            )

        # Blur
        if ve.blur and ve.blur > 0:
            blur_rad = int(min(20, max(1, ve.blur)))
            v_effects_chain.append(f"boxblur=luma_radius={blur_rad}:luma_power=1")

        # Sharpen
        if ve.sharpen and ve.sharpen > 0:
            v_effects_chain.append("unsharp=5:5:1.0:5:5:0.0")

        # Vignette
        if getattr(ve, "vignette", False):
            v_effects_chain.append("vignette=PI/4")

        # Fade in & Fade out transitions
        if ve.fade_in_duration > 0:
            v_effects_chain.append(f"fade=t=in:st=0:d={ve.fade_in_duration:.2f}")
        if ve.fade_out_duration > 0:
            out_st = max(0.0, total_dur - ve.fade_out_duration)
            v_effects_chain.append(f"fade=t=out:st={out_st:.2f}:d={ve.fade_out_duration:.2f}")

        if v_effects_chain:
            v_eff_tag = "v_effects"
            filter_complex_parts.append(f"[{last_v}]{','.join(v_effects_chain)}[{v_eff_tag}]")
            last_v = v_eff_tag

    # 5. Audio Effects: Mute, Bleep, Fades, Normalization
    if last_a:
        # Apply mutes
        for idx, mute in enumerate(timeline.audio_effects.mutes):
            m_starts = resolve_source_range_to_output(timeline, mute.source_start, mute.source_end)
            for m_idx, (m_out_start, m_out_end) in enumerate(m_starts):
                m_tag = f"a_muted_{idx}_{m_idx}"
                filter_complex_parts.append(
                    f"[{last_a}]volume=enable='between(t,{m_out_start:.4f},{m_out_end:.4f})':volume=0[{m_tag}]"
                )
                last_a = m_tag

        # Apply bleeps
        for idx, bleep in enumerate(timeline.audio_effects.bleeps):
            b_starts = resolve_source_range_to_output(timeline, bleep.source_start, bleep.source_end)
            for b_idx, (b_out_start, b_out_end) in enumerate(b_starts):
                b_dur = b_out_end - b_out_start
                if b_dur > 0.01:
                    m_tag = f"a_bmute_{idx}_{b_idx}"
                    filter_complex_parts.append(
                        f"[{last_a}]volume=enable='between(t,{b_out_start:.4f},{b_out_end:.4f})':volume=0[{m_tag}]"
                    )
                    sine_tag = f"sine_{idx}_{b_idx}"
                    mix_tag = f"a_bleeped_{idx}_{b_idx}"
                    filter_complex_parts.append(
                        f"sine=frequency={bleep.frequency_hz}:duration={b_dur:.4f},adelay={int(b_out_start*1000)}|{int(b_out_start*1000)}[{sine_tag}]"
                    )
                    filter_complex_parts.append(
                        f"[{m_tag}][{sine_tag}]amix=inputs=2:duration=first:dropout_transition=0[{mix_tag}]"
                    )
                    last_a = mix_tag

        # Spectral denoising runs on source audio before background music is mixed in.
        noise_reduction_db = timeline.audio_effects.noise_reduction_db
        if noise_reduction_db > 0:
            denoised_tag = "a_denoised"
            filter_complex_parts.append(
                f"[{last_a}]afftdn=nr={noise_reduction_db:.2f}[{denoised_tag}]"
            )
            last_a = denoised_tag

        # Audio Fades
        if ve and (ve.fade_in_duration > 0 or ve.fade_out_duration > 0):
            a_fades = []
            if ve.fade_in_duration > 0:
                a_fades.append(f"afade=t=in:ss=0:d={ve.fade_in_duration:.2f}")
            if ve.fade_out_duration > 0:
                out_st = max(0.0, total_dur - ve.fade_out_duration)
                a_fades.append(f"afade=t=out:st={out_st:.2f}:d={ve.fade_out_duration:.2f}")
            a_fade_tag = "a_faded"
            filter_complex_parts.append(f"[{last_a}]{','.join(a_fades)}[{a_fade_tag}]")
            last_a = a_fade_tag

        # Audio Normalization
        if ve and ve.audio_normalize:
            a_norm_tag = "a_norm"
            filter_complex_parts.append(f"[{last_a}]loudnorm=I=-16:TP=-1.5:LRA=11[{a_norm_tag}]")
            last_a = a_norm_tag

    # 5b. Background Music Mixing
    extra_inputs: List[str] = []
    if timeline.background_music:
        bgm = timeline.background_music
        bgm_file = bgm.track_path
        if not bgm_file or not Path(bgm_file).is_file():
            cand1 = Path("data/assets/ambient_bgm.mp3")
            cand2 = Path("tests/fixtures/ambient_bgm.mp3")
            if cand1.is_file():
                bgm_file = str(cand1.resolve())
            elif cand2.is_file():
                bgm_file = str(cand2.resolve())
        if bgm_file and Path(bgm_file).is_file():
            extra_inputs.extend(["-stream_loop", "-1", "-i", bgm_file])
            bgm_idx = 1
            bgm_vol = bgm.volume or 0.2
            bgm_tag = "a_bgm"
            filter_complex_parts.append(
                f"[{bgm_idx}:a]volume={bgm_vol:.2f},atrim=start=0:end={total_dur:.4f},asetpts=PTS-STARTPTS[{bgm_tag}]"
            )
            if last_a:
                if bgm.ducking_enabled:
                    ducked_bgm_tag = "a_bgm_ducked"
                    # sidechaincompress treats its first input as the signal to
                    # attenuate and its second input as the speech detector.
                    # Keep the original dialogue untouched, then mix the ducked
                    # music back under it.
                    threshold = max(0.001, min(1.0, float(bgm.speech_threshold)))
                    attenuation_db = max(0.0, min(36.0, float(bgm.ducking_attenuation_db)))
                    ratio = max(2.0, min(20.0, 10 ** (attenuation_db / 20.0)))
                    filter_complex_parts.append(
                        f"[{bgm_tag}][{last_a}]sidechaincompress="
                        f"threshold={threshold:.4f}:ratio={ratio:.3f}:attack=20:release=250"
                        f"[{ducked_bgm_tag}]"
                    )
                    bgm_tag = ducked_bgm_tag
                mix_bgm_tag = "a_bgm_mix"
                filter_complex_parts.append(
                    f"[{last_a}][{bgm_tag}]amix=inputs=2:duration=first:dropout_transition=2[{mix_bgm_tag}]"
                )
                last_a = mix_bgm_tag
            else:
                last_a = bgm_tag

    # 6. Captions (via ASS subtitle file with libass)
    ass_path = t_dir / f"subs_{Path(output_path).stem}.ass"
    has_subs = generate_ass_subtitles(timeline, ass_path)
    if has_subs:
        temp_files.append(ass_path)
        escaped_ass = escape_ffmpeg_filter_path(str(ass_path.resolve()))
        filter_complex_parts.append(f"[{last_v}]ass='{escaped_ass}'[v_captioned]")
        last_v = "v_captioned"

    # 7. Text Overlays / Title Cards (via drawtext filter)
    for idx, ovl in enumerate(timeline.text_overlays):
        out_start = ovl.output_start or 0.0
        out_end = ovl.output_end or timeline.total_output_duration
        if ovl.source_start is not None and ovl.source_end is not None:
            mapped = resolve_source_range_to_output(timeline, ovl.source_start, ovl.source_end)
            if mapped:
                out_start, out_end = mapped[0]
            else:
                out_start = ovl.source_start
                out_end = ovl.source_end

        pos = (ovl.position or "center").lower().strip()
        if pos == "top":
            x_expr = "(w-tw)/2"
            y_expr = "60"
            f_size = 44
            box_border = 12
        elif pos == "bottom":
            x_expr = "(w-tw)/2"
            y_expr = "h-th-60"
            f_size = 44
            box_border = 12
        elif pos in ("lower_third", "lowerthird"):
            x_expr = "80"
            y_expr = "h-th-100"
            f_size = 38
            box_border = 10
        elif pos == "watermark":
            x_expr = "w-tw-40"
            y_expr = "40"
            f_size = 28
            box_border = 6
        elif pos in ("credits", "closing"):
            x_expr = "(w-tw)/2"
            y_expr = "(h-th)/2"
            f_size = 48
            box_border = 16
        else: # center
            x_expr = "(w-tw)/2"
            y_expr = "(h-th)/2"
            f_size = 44
            box_border = 12
        safe_text = re.sub(r"[':%]", " ", ovl.text)

        ovl_tag = f"v_ovl_{idx}"
        drawtext = (
            f"drawtext=text='{safe_text}':fontcolor=white:fontsize={f_size}:box=1:boxcolor=black@0.65:boxborderw={box_border}:"
            f"x={x_expr}:y={y_expr}:enable='between(t,{out_start:.4f},{out_end:.4f})'"
        )
        filter_complex_parts.append(f"[{last_v}]{drawtext}[{ovl_tag}]")
        last_v = ovl_tag

    # 8. Constant Frame Rate Defense (normalize variable frame rate)
    v_final = "v_final"
    filter_complex_parts.append(f"[{last_v}]fps={frame_rate}[{v_final}]")
    last_v = v_final

    filter_complex_str = "; ".join(filter_complex_parts)

    ffmpeg_bin = settings.resolve_ffmpeg()
    cmd: List[str] = [
        ffmpeg_bin,
        "-y",
        "-i", media_source_path,
    ]
    cmd.extend(extra_inputs)
    cmd.extend([
        "-filter_complex", filter_complex_str,
        "-map", f"[{last_v}]",
    ])

    if last_a:
        cmd.extend(["-map", f"[{last_a}]"])
        cmd.extend(["-c:a", settings.RENDER_AUDIO_CODEC, "-ar", str(settings.RENDER_AUDIO_SAMPLE_RATE)])
    else:
        cmd.append("-an")

    cmd.extend([
        "-c:v", settings.RENDER_VIDEO_CODEC,
        "-crf", str(quality if quality is not None else settings.RENDER_CRF),
        "-preset", preset or settings.RENDER_PRESET,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ])

    return RenderPlan(command=cmd, temp_files=temp_files)


def resolve_source_range_to_output(timeline: Timeline, src_start: float, src_end: float) -> List[Tuple[float, float]]:
    """Resolve a source interval across retained segments to output intervals."""
    curr_out = 0.0
    intervals: List[Tuple[float, float]] = []

    for index, seg in enumerate(timeline.segments):
        if index:
            curr_out -= seg.transition_duration
        overlap_s = max(seg.source_start, src_start)
        overlap_e = min(seg.source_end, src_end)
        if overlap_s < overlap_e:
            offset_s = (overlap_s - seg.source_start) / seg.speed
            offset_e = (overlap_e - seg.source_start) / seg.speed
            intervals.append((curr_out + offset_s, curr_out + offset_e))
        curr_out += seg.output_duration

    return intervals
