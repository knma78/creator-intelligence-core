"""Deterministic, fail-closed compiler for the first narrated PPT component.

No LLM, TTS, network, or research-media fallback is invoked here. Times in the
source contract are milliseconds; executable times are integer frame indices.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import wave
from pathlib import Path
from typing import Any

from infrastructure.atomic_io import atomic_write_json

VERSION = "1.0"
COMPILER_VERSION = "newton-ppt-2"
CANVAS = {"width": 1280, "height": 720, "fps": 30}
ACTIONS = ("reveal_velocity", "reveal_gravity", "orbit", "conclude")


class AnimationPlanError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnimationPlanError(message)


def _fields(value: Any, fields: set[str], where: str) -> None:
    _require(isinstance(value, dict), f"{where}: 必须是对象")
    _require(set(value) == fields, f"{where}: 字段必须为 {sorted(fields)}")


def _integer(value: Any, low: int, high: int, where: str) -> int:
    _require(type(value) is int and low <= value <= high, f"{where}: 必须为 {low}..{high} 的整数")
    return value


def _string(value: Any, limit: int, where: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit,
             f"{where}: 必须为非空文字，最多 {limit} 字")
    return value


def compile_plan(source: dict, *, source_dir: Path, mode: str = "preview") -> dict:
    """Compile an explicit plan. Verified WAV + reviewed anchors are mandatory
    for production. Preview never labels estimated timings as verified.
    """
    _require(mode in {"preview", "production"}, "mode 无效")
    _fields(source, {"schema_version", "project_id", "canvas", "pages"}, "plan")
    _require(source["schema_version"] == VERSION, "不支持的动画任务版本")
    _require(source["canvas"] == CANVAS, "v1 仅支持 1280×720、30 fps")
    project = _string(source["project_id"], 80, "project_id")
    pages = source["pages"]
    _require(isinstance(pages, list) and 1 <= len(pages) <= 30, "pages 必须有 1..30 页")
    result, ids, global_frame = [], set(), 0
    warnings = []
    for raw in pages:
        _fields(raw, {"id", "title", "component", "narration", "actions", "sources"}, "page")
        page_id = _string(raw["id"], 60, "page.id")
        _require(bool(re.fullmatch(r"[a-zA-Z0-9_-]+", page_id)) and page_id not in ids,
                 "页面 ID 必须唯一且只含英文字母数字下划线或短横线")
        ids.add(page_id)
        _string(raw["title"], 22, f"{page_id}.title")
        component = raw["component"]
        _fields(component, {"name", "version", "start_angle_deg", "sweep_deg"}, "component")
        _require(component["name"] == "newton_orbit" and component["version"] == "1",
                 "不支持的组件或版本，禁止回退为背景图")
        _integer(component["start_angle_deg"], -70, -30, "start_angle_deg")
        _integer(component["sweep_deg"], 30, 120, "sweep_deg")
        sources = raw["sources"]
        _require(isinstance(sources, list) and 1 <= len(sources) <= 12, "必须提供事实来源")
        for citation in sources:
            _string(citation, 1000, "source")
            _require(citation.startswith("https://"), "来源必须是 HTTPS URL")
        n = raw["narration"]
        _fields(n, {"text", "sha256", "duration_ms", "timing_kind", "reviewer", "audio", "anchors"}, "narration")
        text = _string(n["text"], 2000, "narration.text")
        _require(n["sha256"] == text_hash(text), f"{page_id}: 文稿指纹不匹配，需重新绑定锚点")
        duration = _integer(n["duration_ms"], 8000, 60000, "duration_ms")
        _require(isinstance(n["timing_kind"], str) and n["timing_kind"] in {"draft", "reviewed"}, "timing_kind 无效")
        _require(isinstance(n["reviewer"], str), "reviewer 必须为文字")
        audio = None
        if n["audio"] is not None:
            _fields(n["audio"], {"path", "sha256"}, "audio")
            rel = Path(_string(n["audio"]["path"], 300, "audio.path"))
            _require(not rel.is_absolute() and ".." not in rel.parts, "音频必须为任务目录内的相对路径")
            path = (source_dir.resolve() / rel).resolve()
            _require(path.is_relative_to(source_dir.resolve()) and path.is_file(), "音频缺失或越出任务目录")
            _require(path.suffix.lower() == ".wav", "v1 仅支持 PCM WAV 音频")
            _require(file_hash(path) == n["audio"]["sha256"], "音频指纹不匹配")
            try:
                with wave.open(str(path), "rb") as wav:
                    actual_ms = wav.getnframes() * 1000 / wav.getframerate()
            except (wave.Error, EOFError) as exc:
                raise AnimationPlanError("不是可读取的 PCM WAV") from exc
            _require(abs(actual_ms - duration) <= 100, "音频时长与任务时长不一致")
            audio = {"path": str(path), "sha256": n["audio"]["sha256"]}
        if mode == "production":
            _require(audio is not None and n["timing_kind"] == "reviewed" and bool(n["reviewer"].strip()),
                     f"{page_id}: 正式执行需要真实音频及已复核时间锚点")
        if n["timing_kind"] != "reviewed" or audio is None:
            warnings.append(f"{page_id}: 仅为未配音时序预览，不能作为已完成音画同步的成片")
        anchors, previous_char, previous_time = {}, 0, 0
        _require(isinstance(n["anchors"], list) and 1 <= len(n["anchors"]) <= 100, "anchors 无效")
        for anchor in n["anchors"]:
            _fields(anchor, {"id", "start_char", "end_char", "quote", "start_ms", "end_ms"}, "anchor")
            aid = _string(anchor["id"], 60, "anchor.id")
            _require(aid not in anchors, "锚点 ID 重复")
            a = _integer(anchor["start_char"], previous_char, len(text) - 1, "start_char")
            b = _integer(anchor["end_char"], a + 1, len(text), "end_char")
            start = _integer(anchor["start_ms"], previous_time, duration - 1, "start_ms")
            end = _integer(anchor["end_ms"], start + 1, duration, "end_ms")
            _require(text[a:b] == anchor["quote"], "锚点文字与旁白不一致")
            anchors[aid] = start
            previous_char, previous_time = b, end
        _require(isinstance(raw["actions"], list) and len(raw["actions"]) == 4, "v1 必须提供四个明确动作")
        actions, previous_start = [], -1
        for expected, action in zip(ACTIONS, raw["actions"]):
            _fields(action, {"op", "anchor", "offset_ms", "duration_ms"}, "action")
            _require(action["op"] == expected, f"动作顺序必须为 {ACTIONS}")
            _string(action['anchor'], 60, 'action.anchor')
            _require(action["anchor"] in anchors, f"动作锚点不存在: {action['anchor']}")
            offset = _integer(action["offset_ms"], 0, 10000, "offset_ms")
            length = _integer(action["duration_ms"], 1000 if expected == "orbit" else 0,
                              10000 if expected == "orbit" else 0, "action.duration_ms")
            start_ms = anchors[action["anchor"]] + offset
            start_frame = round(start_ms * CANVAS["fps"] / 1000)
            end_frame = round((start_ms + length) * CANVAS["fps"] / 1000)
            _require(start_frame > previous_start and start_ms + length < duration,
                     "动作必须递增且在本页结束前完成")
            actions.append({"op": expected, "start_frame": start_frame, "end_frame": end_frame})
            previous_start = start_frame
        _require(actions[3]["start_frame"] >= actions[2]["end_frame"], "结论不能在轨道演示完成前出现")
        frame_count = round(duration * CANVAS["fps"] / 1000)
        payload = {"id": page_id, "title": raw["title"], "component": component,
                   "narration": {**n, "audio": audio}, "actions": actions, "sources": sources,
                   "duration_frames": frame_count}
        # Absolute paths and earlier page durations do not change this page's identity.
        fingerprint = digest({"compiler": COMPILER_VERSION, "canvas": CANVAS, "page": raw})
        result.append({**payload, "fingerprint": fingerprint, "global_start_frame": global_frame})
        global_frame += frame_count
    return {"schema_version": VERSION, "compiler_version": COMPILER_VERSION,
            "project_id": project, "canvas": dict(CANVAS), "mode": mode,
            "warnings": warnings, "duration_frames": global_frame, "pages": result}


def save_compilation(plan: dict, output_dir: Path) -> dict:
    """Cache immutable page-local tasks; publish manifest last. No source deletion."""
    output_dir.mkdir(parents=True, exist_ok=True)
    reused, changed = [], []
    for page in plan["pages"]:
        local = {k: v for k, v in page.items() if k != "global_start_frame"}
        path = output_dir / "pages" / f"{page['id']}-{page['fingerprint']}.json"
        # Verify cached bytes rather than trusting the filename.
        try:
            valid = json.loads(path.read_text(encoding="utf-8")) == local
        except (OSError, ValueError):
            valid = False
        if valid:
            reused.append(page["id"])
        else:
            atomic_write_json(path, local)
            changed.append(page["id"])
    atomic_write_json(output_dir / "compiled.json", plan)
    report = {"changed_pages": changed, "reused_pages": reused, "warnings": plan["warnings"],
              "scope": "页面任务增量缓存；PPTX 输出仍重新封装，不保证二进制逐字节一致"}
    atomic_write_json(output_dir / "compile_report.json", report)
    return report


def orbit_state(component: dict, progress: float) -> dict:
    """Screen coordinates, clockwise. Gravity is radial; velocity tangential."""
    theta = math.radians(component["start_angle_deg"] + component["sweep_deg"] * progress)
    radial = (math.cos(theta), math.sin(theta))
    return {"moon": (865 + 150 * radial[0], 350 + 150 * radial[1]),
            "gravity": (-radial[0], -radial[1]), "velocity": (-radial[1], radial[0])}
