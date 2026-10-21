from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from infrastructure.atomic_io import atomic_write_text


_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
_SEMANTIC_SPLIT = re.compile(r"(?<=[，,。！？!?；;、])\s*")
_VTT_TIME = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
_HTML_TAG = re.compile(r"<[^>]+>")


def parse_vtt(path: Path) -> list[dict[str, Any]]:
    lines = Path(path).read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines()
    cues: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        match = _VTT_TIME.search(lines[index])
        if not match:
            index += 1
            continue
        text_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text_lines.append(_HTML_TAG.sub("", lines[index]).strip())
            index += 1
        text = _join_caption_lines(text_lines)
        if text:
            start = _timestamp_seconds(match.group("start"))
            end = _timestamp_seconds(match.group("end"))
            if end > start:
                cues.append({"start": start, "end": end, "text": text})
        index += 1
    return cues


def compact_caption_cues(
    cues: list[dict[str, Any]],
    *,
    max_display_units: int = 28,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        if current is None:
            current = dict(cue)
            continue
        combined = str(current["text"]) + text
        span = float(cue["end"]) - float(current["start"])
        gap = float(cue["start"]) - float(current["end"])
        if (
            display_units(combined) <= max_display_units
            and span <= 3.8
            and gap <= 0.6
        ):
            current["text"] = combined
            current["end"] = cue["end"]
        else:
            compacted.append(current)
            current = dict(cue)
    if current is not None:
        compacted.append(current)
    return compacted


def normalize_caption_cues(
    cues: list[dict[str, Any]],
    *,
    max_display_units: int = 24,
) -> list[dict[str, Any]]:
    """Split dense captions and enforce a monotonic, gap-safe timeline."""

    normalized: list[dict[str, Any]] = []
    previous_end = 0.0
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        start = max(previous_end, float(cue.get("start") or 0))
        end = max(start + 0.12, float(cue.get("end") or start))
        chunks = _split_display_chunks(text, max_display_units)
        weights = [max(1, display_units(chunk)) for chunk in chunks]
        total_weight = sum(weights)
        cursor = start
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            chunk_end = (
                end
                if index == len(chunks) - 1
                else cursor + (end - start) * weight / total_weight
            )
            actual_end = max(cursor + 0.001, chunk_end)
            normalized.append(
                {
                    "start": round(cursor, 3),
                    "end": round(actual_end, 3),
                    "text": chunk,
                }
            )
            cursor = actual_end
        previous_end = cursor
    return normalized


def semantic_caption_cues(
    cues: list[dict[str, Any]],
    *,
    script: str | None = None,
    max_display_units: int = 32,
    min_duration: float = 0.8,
    max_duration: float = 6.0,
) -> list[dict[str, Any]]:
    """Realign TTS cues by sentence/phrase boundaries while preserving real audio timing.

    If ``script`` is supplied, the returned cues are aligned to the original script text
    so that words are never split across cues (e.g. "交" / "代"). Timing is derived from
    the TTS-produced cues, not from a per-character estimate.
    """
    if script:
        chunks = _semantic_chunks(script.strip(), max_display_units)
        char_times = _build_char_time_map(cues)
        # Verify the cue text covers the script (ignoring whitespace).
        normalized_script = _normalize_text(script)
        normalized_cues = _normalize_text("".join(str(c.get("text") or "") for c in cues))
        if normalized_script and normalized_cues and normalized_script == normalized_cues:
            aligned = _align_chunks_to_times(chunks, script, char_times)
            if aligned:
                return _finalize_cues(aligned, min_duration, max_duration, max_display_units)

    # Fallback: work directly with the cue text when no script is available.
    return _realign_cue_text(cues, max_display_units, min_duration, max_duration)


def _build_char_time_map(cues: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    """Map every character from the raw cues to its estimated [start, end) interval."""
    entries: list[tuple[str, float, float]] = []
    for cue in cues:
        text = str(cue.get("text") or "")
        start = float(cue.get("start") or 0)
        end = float(cue.get("end") or start)
        duration = max(0, end - start)
        total_units = max(1, display_units(text))
        unit_duration = duration / total_units
        cursor = start
        for character in text:
            character_units = display_units(character)
            character_end = cursor + character_units * unit_duration
            entries.append((character, cursor, character_end))
            cursor = character_end
    return entries


def _align_chunks_to_times(
    chunks: list[str],
    script: str,
    char_times: list[tuple[str, float, float]],
) -> list[dict[str, Any]]:
    """Map each semantic chunk of ``script`` to the real timing of its first/last characters."""
    # Build a position map: for each index in the whitespace-normalized script, store time.
    normalized_script = _normalize_text(script)
    if len(normalized_script) != len(char_times):
        return []
    result: list[dict[str, Any]] = []
    normalized_cursor = 0
    for chunk in chunks:
        chunk_normalized = _normalize_text(chunk)
        length = len(chunk_normalized)
        if length == 0:
            continue
        # Locate this chunk in the normalized script.
        start_idx = normalized_script.find(chunk_normalized, normalized_cursor)
        if start_idx < 0:
            return []
        end_idx = start_idx + length
        chunk_start = char_times[start_idx][1]
        chunk_end = char_times[min(end_idx - 1, len(char_times) - 1)][2]
        result.append(
            {
                "start": round(chunk_start, 3),
                "end": round(max(chunk_start + 0.05, chunk_end), 3),
                "text": _clean_caption_text(chunk),
            }
        )
        normalized_cursor = end_idx
    return result


def _finalize_cues(
    cues: list[dict[str, Any]],
    min_duration: float,
    max_duration: float,
    max_display_units: int,
) -> list[dict[str, Any]]:
    """Merge short cues and enforce monotonic, gap-safe timing."""
    # Merge cues that are shorter than min_duration into the next cue when possible.
    merged: list[dict[str, Any]] = []
    buffer: dict[str, Any] | None = None
    for cue in cues:
        if _is_punctuation_only(cue["text"]):
            continue
        if buffer is None:
            buffer = dict(cue)
            continue
        combined_text = buffer["text"] + cue["text"]
        combined_duration = cue["end"] - buffer["start"]
        if (
            (buffer["end"] - buffer["start"]) < min_duration
            and display_units(combined_text) <= max_display_units
            and combined_duration <= max_duration
        ):
            buffer["text"] = combined_text
            buffer["end"] = cue["end"]
        else:
            merged.append(buffer)
            buffer = dict(cue)
    if buffer is not None:
        merged.append(buffer)

    # Ensure monotonic timeline.
    final: list[dict[str, Any]] = []
    previous_end = 0.0
    for cue in merged:
        cue["start"] = max(previous_end, cue["start"])
        cue["end"] = max(cue["start"] + min_duration, cue["end"])
        final.append(cue)
        previous_end = cue["end"]
    return final


def _realign_cue_text(
    cues: list[dict[str, Any]],
    max_display_units: int,
    min_duration: float,
    max_duration: float,
) -> list[dict[str, Any]]:
    """Fallback realignment when the original script is not available."""
    # Merge cues that are obviously fragments of the same phrase (tiny gap).
    merged: list[dict[str, Any]] = []
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text or _is_punctuation_only(text):
            continue
        if not merged:
            merged.append({"start": float(cue["start"]), "end": float(cue["end"]), "text": text})
            continue
        last = merged[-1]
        gap = float(cue["start"]) - last["end"]
        combined_text = last["text"] + text
        if gap <= 0.08 and display_units(combined_text) <= max_display_units + 4:
            last["text"] = combined_text
            last["end"] = float(cue["end"])
            continue
        merged.append({"start": float(cue["start"]), "end": float(cue["end"]), "text": text})

    # Split long cues at semantic boundaries and redistribute original timing.
    final: list[dict[str, Any]] = []
    for cue in merged:
        text = cue["text"]
        start = cue["start"]
        end = cue["end"]
        if display_units(text) <= max_display_units:
            final.append({"start": round(start, 3), "end": round(end, 3), "text": _clean_caption_text(text)})
            continue
        pieces = _semantic_chunks(text, max_display_units)
        weights = [max(1, display_units(piece)) for piece in pieces]
        total_weight = sum(weights)
        cursor = start
        for index, (piece, weight) in enumerate(zip(pieces, weights)):
            piece_end = end if index == len(pieces) - 1 else cursor + (end - start) * weight / total_weight
            piece_end = max(cursor + 0.05, piece_end)
            final.append({"start": round(cursor, 3), "end": round(piece_end, 3), "text": _clean_caption_text(piece)})
            cursor = piece_end

    return _finalize_cues(final, min_duration, max_duration, max_display_units)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def write_srt(cues: list[dict[str, Any]], path: Path) -> Path:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(float(cue['start']))} --> "
            f"{_srt_timestamp(float(cue['end']))}\n{cue['text']}"
        )
    if not blocks:
        raise ValueError("不能写入空字幕。")
    return atomic_write_text(Path(path), "\n\n".join(blocks) + "\n")


def write_vtt(cues: list[dict[str, Any]], path: Path) -> Path:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            f"{_vtt_timestamp(float(cue['start']))} --> "
            f"{_vtt_timestamp(float(cue['end']))}\n{cue['text']}"
        )
    if len(blocks) == 1:
        raise ValueError("不能写入空时间轴。")
    return atomic_write_text(Path(path), "\n\n".join(blocks) + "\n")


def write_ass(
    cues: list[dict[str, Any]],
    path: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    font_name: str = "Microsoft YaHei",
    font_size: int = 20,
    margin_v: int = 60,
    alignment: int = 2,
) -> Path:
    """Write an ASS subtitle file with explicit canvas resolution and bottom-safe style."""
    if not cues:
        raise ValueError("不能写入空字幕。")
    header = (
        "[Script Info]\n"
        "Title: ContentResearchGenerated\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.601\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00101010,"
        f"&H00000000,0,0,0,0,100,100,0,0,1,3,1,{alignment},40,40,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [header]
    for cue in cues:
        start = _ass_timestamp(float(cue["start"]))
        end = _ass_timestamp(float(cue["end"]))
        text = _ass_escape(str(cue["text"] or ""))
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return atomic_write_text(Path(path), "".join(lines))


def estimate_caption_cues(
    script: str,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    chunks = split_script(script, target_units=26)
    weights = [max(1, display_units(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    cues: list[dict[str, Any]] = []
    start = 0.0
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        end = (
            duration_seconds
            if index == len(chunks) - 1
            else min(
                duration_seconds,
                start + duration_seconds * weight / total_weight,
            )
        )
        cues.append(
            {
                "start": round(start, 3),
                "end": round(max(start + 0.1, end), 3),
                "text": chunk,
            }
        )
        start = end
    return cues


def split_script(script: str, *, target_units: int = 42) -> list[str]:
    clean = re.sub(r"[ \t]+", " ", script.strip())
    sentences = [
        item.strip()
        for item in _SENTENCE_SPLIT.split(clean)
        if item.strip()
    ]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and display_units(current + sentence) > target_units:
            chunks.append(current)
            current = ""
        while display_units(sentence) > target_units * 2:
            pieces = _split_display_chunks(sentence, target_units)
            if len(pieces) <= 1:
                break
            chunks.extend(pieces[:-1])
            sentence = pieces[-1]
        current += sentence
    if current:
        chunks.append(current)
    return chunks or [clean]


def display_units(text: str) -> int:
    return sum(
        2 if "\u3400" <= character <= "\u9fff" else 1
        for character in text
    )


def _semantic_chunks(text: str, max_display_units: int) -> list[str]:
    """Split long text at phrase boundaries; fall back to display-unit chunks only when necessary."""
    if display_units(text) <= max_display_units:
        return [_clean_caption_text(text)]
    # Prefer splitting at semantic separators.
    phrases = [p.strip() for p in _SEMANTIC_SPLIT.split(text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for phrase in phrases:
        phrase = _clean_caption_text(phrase)
        if not phrase:
            continue
        if current and display_units(current + phrase) > max_display_units:
            chunks.append(current)
            current = ""
        if display_units(phrase) > max_display_units:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_display_chunks(phrase, max_display_units))
        else:
            current += phrase
    if current:
        chunks.append(current)
    return chunks or _split_display_chunks(text, max_display_units)


def _split_display_chunks(
    text: str,
    max_display_units: int,
) -> list[str]:
    if display_units(text) <= max_display_units:
        return [text]
    chunks: list[str] = []
    current = ""
    tokens = re.findall(r"[A-Za-z0-9_]+(?:['’-][A-Za-z0-9_]+)*|\s+|.", text)
    for token in tokens:
        if token.isspace() and not current:
            continue
        candidate = current + token
        if current and display_units(candidate) > max_display_units:
            chunks.append(current.strip())
            current = token.lstrip()
            continue
        if not current and display_units(token) > max_display_units:
            for character in token:
                candidate = current + character
                if current and display_units(candidate) > max_display_units:
                    chunks.append(current.strip())
                    current = character
                else:
                    current = candidate
            continue
        current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _clean_caption_text(text: str) -> str:
    text = text.strip()
    # Avoid a single punctuation mark or a trailing orphan punctuation on its own cue.
    text = _strip_trailing_punctuation(text)
    return text


def _is_punctuation_only(text: str) -> bool:
    return all(unicodedata.category(c).startswith("P") or c.isspace() for c in text)


def _strip_trailing_punctuation(text: str) -> str:
    # Keep sentence-ending punctuation, but remove a lone trailing comma/pause mark.
    while text and text[-1] in "，,、":
        text = text[:-1].strip()
    return text


def _timestamp_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _vtt_timestamp(seconds: float) -> str:
    return _srt_timestamp(seconds).replace(",", ".")


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    # Escape ASS field separators and special characters.
    text = text.replace("\\", "\\\\")
    text = text.replace(",", "\\,")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    # Newlines within a cue become ASS line breaks.
    text = text.replace("\n", "\\N")
    return text


def _join_caption_lines(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    output = cleaned[0]
    for line in cleaned[1:]:
        separator = ""
        if (
            output
            and line
            and output[-1].isascii()
            and output[-1].isalnum()
            and line[0].isascii()
            and line[0].isalnum()
        ):
            separator = " "
        output += separator + line
    return output
