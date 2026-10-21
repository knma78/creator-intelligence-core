from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from config import Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
    run_cancellable_call,
)
from integrations.local_skills import (
    get_native_english_review_skill_status,
    load_native_english_review_skill,
)


DIMENSION_MAX = {
    "native_fluency": 25,
    "dialogue_authenticity": 15,
    "narrative_clarity": 15,
    "cultural_accessibility": 10,
    "dialect_consistency": 5,
    "read_aloud_clarity": 10,
    "web_serial_craft": 20,
}
DIMENSION_LABELS = {
    "native_fluency": "母语自然度",
    "dialogue_authenticity": "对白真实性",
    "narrative_clarity": "叙事清晰度",
    "cultural_accessibility": "文化可理解性",
    "dialect_consistency": "地区英语一致性",
    "read_aloud_clarity": "朗读清晰度",
    "web_serial_craft": "中国网文机制保留",
}
WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+")
SENTENCE_RE = re.compile(r"(?<=[.!?])(?:[\"'’”)]*)\s+")


def get_english_review_runtime_status(settings: Settings) -> dict[str, Any]:
    harper_cli = settings.english_review_harper_cli
    return {
        "available": bool(settings.llm_api_key),
        "review_model": settings.novel_review_model,
        "skill": get_native_english_review_skill_status(
            settings.native_english_review_skill_path
        ),
        "harper": {
            "available": harper_cli.is_file(),
            "engine": "harper-cli",
            "path": str(harper_cli),
        },
        "readability": {
            "available": True,
            "engine": "builtin-readability-v2",
            "dependency_free": True,
        },
    }


def review_english_fiction(
    text: str,
    settings: Settings,
    *,
    locale: str,
    auto_revise: bool = True,
    progress_callback: Callable[[str, int, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if locale not in {"en-US", "en-GB"}:
        raise ValueError(f"不支持的英语地区：{locale}")
    if not settings.llm_api_key:
        raise RuntimeError("尚未配置 LLM_API_KEY，无法执行英语母语化审稿。")
    text = str(text or "").strip()
    if not text:
        raise ValueError("没有可供英语审稿的正文。")

    raise_if_cancelled(cancel_requested)
    skill = load_native_english_review_skill(
        settings.native_english_review_skill_path
    )
    _progress(progress_callback, "英文硬规则检查", 1, "正在运行 Harper 与可读性检查。")
    initial_deterministic = run_deterministic_checks(
        text,
        settings,
        locale=locale,
        cancel_requested=cancel_requested,
    )
    _progress(progress_callback, "英语母语审稿", 2, "正在进行独立母语化评分。")
    initial_review = _judge_text(
        text,
        settings,
        locale=locale,
        deterministic=initial_deterministic,
        skill=skill,
        cancel_requested=cancel_requested,
    )

    final_text = text
    final_review = initial_review
    final_deterministic = initial_deterministic
    revised = False
    if auto_revise and initial_review["decision"] != "native-ready":
        _progress(progress_callback, "英语自动修订", 3, "质检未通过，正在按问题清单修订一次。")
        final_text = _revise_text(
            text,
            initial_review,
            settings,
            locale=locale,
            cancel_requested=cancel_requested,
        )
        revised = final_text.strip() != text.strip()
        raise_if_cancelled(cancel_requested)
        _progress(progress_callback, "英语复检", 4, "正在复查修订后的英语成品。")
        final_deterministic = run_deterministic_checks(
            final_text,
            settings,
            locale=locale,
            cancel_requested=cancel_requested,
        )
        final_review = _judge_text(
            final_text,
            settings,
            locale=locale,
            deterministic=final_deterministic,
            skill=skill,
            cancel_requested=cancel_requested,
        )

    return {
        "schema_version": "1.0",
        "locale": locale,
        "review_model": settings.novel_review_model,
        "skill": skill.status(),
        "revised": revised,
        "original_text": text,
        "final_text": final_text,
        "initial": {
            "deterministic": initial_deterministic,
            "review": initial_review,
        },
        "final": {
            "deterministic": final_deterministic,
            "review": final_review,
        },
    }


def run_deterministic_checks(
    text: str,
    settings: Settings,
    *,
    locale: str,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    return {
        "harper": _run_harper(
            text,
            settings,
            locale=locale,
            cancel_requested=cancel_requested,
        ),
        "readability": _readability_metrics(text, locale),
        "dialect_fallback": _dialect_fallback(text, locale),
    }


def render_review_markdown(result: dict[str, Any]) -> str:
    initial = result["initial"]["review"]
    final = result["final"]["review"]
    lines = [
        "# 英语母语化质检报告",
        "",
        f"- 地区：{result['locale']}",
        f"- 审稿模型：{result['review_model']}",
        f"- 自动修订：{'是' if result['revised'] else '否'}",
        f"- 初审：{initial['score']}/100 · {initial['decision']}",
        f"- 终审：{final['score']}/100 · {final['decision']}",
        "",
        "## 终审维度",
        "",
    ]
    for key, maximum in DIMENSION_MAX.items():
        item = final["dimensions"][key]
        lines.append(
            f"- {DIMENSION_LABELS[key]}：{item['score']}/{maximum} — "
            f"{item['rationale']}"
        )
    lines.extend(["", "## 主要问题", ""])
    issues = final.get("issues") or []
    if not issues:
        lines.append("未发现需要阻止交付的母语化问题。")
    for index, issue in enumerate(issues, start=1):
        lines.extend(
            [
                f"### {index}. {issue['severity']}",
                "",
                f"- 原句：`{issue['excerpt']}`",
                f"- 说明：{issue['explanation']}",
                f"- 建议：{issue['suggestion']}",
                "",
            ]
        )
    lines.extend(["## 修订优先级", ""])
    priorities = final.get("revision_priorities") or []
    lines.extend(f"- {item}" for item in priorities)
    lines.extend(
        [
            "",
            "## 机器指标说明",
            "",
            "Harper 与可读性公式只能提供语法、地区拼写和阅读难度信号；"
            "最终判断来自独立审稿评分。出版级交付仍建议抽样交给目标地区母语读者。",
            "",
        ]
    )
    return "\n".join(lines)


def _run_harper(
    text: str,
    settings: Settings,
    *,
    locale: str,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    status = get_english_review_runtime_status(settings)["harper"]
    if not status["available"]:
        return {
            "available": False,
            "engine": "harper-cli",
            "locale": locale,
            "reason": "Harper 官方 Windows CLI 尚未安装。",
            "finding_count": 0,
            "findings": [],
        }
    dialect = "us" if locale == "en-US" else "gb"
    command = [
        str(settings.english_review_harper_cli),
        "lint",
        "--format",
        "json",
        "--quiet",
        "--no-color",
        "--dialect",
        dialect,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            encoding="utf-8",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_path = Path(temporary.name)
        command.append(str(temporary_path))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        try:
            stdout, stderr = run_cancellable_call(
                lambda: process.communicate(timeout=60),
                cancel_requested,
                on_cancel=process.terminate,
            )
        except JobCancelledError:
            raise
        except Exception:
            if process.poll() is None:
                process.kill()
            raise
        combined = "\n".join(item for item in (stdout.strip(), stderr.strip()) if item)
        findings = _parse_harper_json(stdout, text)
        # Harper returns a non-zero status when lints are found, so diagnostics
        # in the output are a successful check rather than a runtime failure.
        if process.returncode != 0 and not findings:
            raise RuntimeError(combined or f"Harper CLI 退出码 {process.returncode}")
        return {
            "available": True,
            "engine": "harper-cli",
            "locale": locale,
            "finding_count": len(findings),
            "findings": findings,
            "diagnostics": stderr.strip()[:2000],
        }
    except JobCancelledError:
        raise
    except Exception as exc:
        return {
            "available": False,
            "engine": "harper-cli",
            "locale": locale,
            "reason": str(exc),
            "finding_count": 0,
            "findings": [],
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _readability_metrics(text: str, locale: str) -> dict[str, Any]:
    words = WORD_RE.findall(text)
    sentences = [item.strip() for item in SENTENCE_RE.split(text) if item.strip()]
    word_count = len(words)
    sentence_count = max(len(sentences), 1)
    syllable_counts = [_estimate_syllables(word) for word in words]
    syllables = sum(syllable_counts)
    complex_words = sum(value >= 3 for value in syllable_counts)
    letters = sum(len(re.sub(r"[^A-Za-z]", "", word)) for word in words)
    words_per_sentence = word_count / sentence_count
    syllables_per_word = syllables / max(word_count, 1)
    letters_per_100_words = 100 * letters / max(word_count, 1)
    sentences_per_100_words = 100 * len(sentences) / max(word_count, 1)
    complex_percent = 100 * complex_words / max(word_count, 1)
    flesch_kincaid = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
    automated_readability = (
        4.71 * letters / max(word_count, 1) + 0.5 * words_per_sentence - 21.43
    )
    coleman_liau = 0.0588 * letters_per_100_words - 0.296 * sentences_per_100_words - 15.8
    gunning_fog = 0.4 * (words_per_sentence + complex_percent)
    smog = 1.043 * math.sqrt(complex_words * 30 / sentence_count) + 3.1291
    grade_values = [flesch_kincaid, automated_readability, coleman_liau, gunning_fog, smog]
    estimated_grade = max(0.0, sorted(grade_values)[len(grade_values) // 2])
    result: dict[str, Any] = {
        "available": True,
        "engine": "builtin-readability-v2",
        "dependency_free": True,
        "locale": locale,
        "word_count": word_count,
        "sentence_count": len(sentences),
        "syllable_count": syllables,
        "average_words_per_sentence": round(words_per_sentence, 2),
        "long_sentence_count": sum(
            1 for sentence in sentences if len(WORD_RE.findall(sentence)) > 30
        ),
        "complex_word_count": complex_words,
        "flesch_reading_ease": round(
            206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word,
            2,
        ),
        "flesch_kincaid_grade": round(max(0.0, flesch_kincaid), 2),
        "automated_readability_index": round(max(0.0, automated_readability), 2),
        "coleman_liau_index": round(max(0.0, coleman_liau), 2),
        "gunning_fog_index": round(max(0.0, gunning_fog), 2),
        "smog_index": round(max(0.0, smog), 2),
        "estimated_grade": round(estimated_grade, 1),
        "estimated_reading_seconds": round(word_count / 238 * 60, 1),
    }
    return result


def _parse_harper_json(output: str, text: str) -> list[dict[str, Any]]:
    documents = json.loads(output or "[]")
    if not isinstance(documents, list):
        raise ValueError("Harper CLI JSON 根节点不是数组。")
    findings: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        for item in document.get("lints") or []:
            if not isinstance(item, dict):
                continue
            span = item.get("span") or {}
            start = max(0, int(span.get("char_start") or 0))
            end = max(start, int(span.get("char_end") or start))
            findings.append(
                {
                    "start": start,
                    "end": end,
                    "line": int(item.get("line") or 0),
                    "column": int(item.get("column") or 0),
                    "rule": str(item.get("rule") or ""),
                    "kind": str(item.get("kind") or ""),
                    "priority": int(item.get("priority") or 0),
                    "excerpt": str(item.get("matched_text") or text[start:end])[:300],
                    "message": str(item.get("message") or "")[:800],
                    "suggestions": [
                        str(value)[:600] for value in (item.get("suggestions") or [])[:10]
                    ],
                }
            )
    return findings[:200]


def _dialect_fallback(text: str, locale: str) -> dict[str, Any]:
    pairs = (
        ("color", "colour"),
        ("favorite", "favourite"),
        ("honor", "honour"),
        ("center", "centre"),
        ("meter", "metre"),
        ("theater", "theatre"),
        ("defense", "defence"),
        ("license", "licence"),
        ("traveled", "travelled"),
        ("traveling", "travelling"),
    )
    expected_index = 0 if locale == "en-US" else 1
    findings = []
    for pair in pairs:
        wrong = pair[1 - expected_index]
        expected = pair[expected_index]
        for match in re.finditer(rf"\b{re.escape(wrong)}\b", text, re.I):
            findings.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "excerpt": match.group(0),
                    "message": f"{locale} 通常使用 {expected}。",
                    "suggestion": expected,
                }
            )
    return {
        "engine": "builtin-dialect",
        "locale": locale,
        "finding_count": len(findings),
        "findings": findings,
    }


def _estimate_syllables(word: str) -> int:
    value = re.sub(r"[^a-z]", "", word.lower())
    if not value:
        return 0
    groups = len(re.findall(r"[aeiouy]+", value))
    if value.endswith("e") and not value.endswith(("le", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


def _judge_text(
    text: str,
    settings: Settings,
    *,
    locale: str,
    deterministic: dict[str, Any],
    skill: Any,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    rubric = skill.references["review-rubric.md"]
    clipped = text[: settings.llm_max_chars]
    prompt = f"""
你是与创作过程隔离的英语小说母语化审稿人。目标地区是 {locale}。
严格依据评分表评分，不因为文本由 AI 生成或已经修订而放宽标准。

{rubric}

确定性检查：
{json.dumps(deterministic, ensure_ascii=False)[:12000]}

待审正文：
{clipped}

只输出 JSON。dimensions 必须包含以下键，每项提供 score 和中文 rationale：
{json.dumps(DIMENSION_MAX, ensure_ascii=False)}
还必须包含 blockers、issues、strengths、revision_priorities、human_review_recommended。
issues 每项包含 severity（blocker/major/minor）、excerpt、explanation（中文）、suggestion（英文）。
""".strip()
    data = _llm_json(
        prompt,
        settings,
        system=(
            "You are a strict native-English fiction editor. Evaluate independently, "
            "return JSON only, and explain editorial findings in Chinese."
        ),
        temperature=0.1,
        cancel_requested=cancel_requested,
    )
    return _normalise_review(data, locale)


def _revise_text(
    text: str,
    review: dict[str, Any],
    settings: Settings,
    *,
    locale: str,
    cancel_requested: Callable[[], bool] | None,
) -> str:
    locale_name = "American" if locale == "en-US" else "British"
    prompt = f"""
Revise the English fiction below using the editorial report.

Requirements:
- Use native, publication-quality {locale_name} English consistently.
- Preserve all story facts, viewpoint, tense, character intent, progression, payoffs, and chapter hook.
- Fix blockers and major issues before minor polish.
- Keep Chinese cultural concepts when intended, but make them inferable through unobtrusive context.
- Output only the revised English Markdown, with no commentary.

Editorial report:
{json.dumps(review, ensure_ascii=False)[:16000]}

Original fiction:
{text[: settings.llm_max_chars]}
""".strip()
    return _llm_text(
        prompt,
        settings,
        system="You are a native-English fiction line and developmental editor.",
        temperature=0.3,
        cancel_requested=cancel_requested,
    )


def _llm_json(
    prompt: str,
    settings: Settings,
    *,
    system: str,
    temperature: float,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    content = _llm_text(
        prompt,
        settings,
        system=system,
        temperature=temperature,
        response_format={"type": "json_object"},
        cancel_requested=cancel_requested,
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise RuntimeError("英语审稿模型没有返回有效 JSON。")
        return json.loads(match.group(0))


def _llm_text(
    prompt: str,
    settings: Settings,
    *,
    system: str,
    temperature: float,
    cancel_requested: Callable[[], bool] | None,
    response_format: dict[str, str] | None = None,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 openai SDK，无法执行英语审稿。") from exc
    client_kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**client_kwargs)
    request_kwargs: dict[str, Any] = {
        "model": settings.novel_review_model,
        "temperature": temperature,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if response_format:
        request_kwargs["response_format"] = response_format
    try:
        response = run_cancellable_call(
            lambda: client.chat.completions.create(**request_kwargs),
            cancel_requested,
            on_cancel=getattr(client, "close", None),
        )
        chunks: list[str] = []
        try:
            for chunk in response:
                raise_if_cancelled(cancel_requested)
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    content = getattr(getattr(choices[0], "delta", None), "content", None)
                    if content:
                        chunks.append(str(content))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        result = "".join(chunks).strip()
        if not result:
            raise RuntimeError("英语审稿模型没有返回内容。")
        return result
    finally:
        close_client = getattr(client, "close", None)
        if callable(close_client):
            close_client()


def _normalise_review(data: dict[str, Any], locale: str) -> dict[str, Any]:
    raw_dimensions = data.get("dimensions") or {}
    dimensions: dict[str, dict[str, Any]] = {}
    score = 0
    for key, maximum in DIMENSION_MAX.items():
        item = raw_dimensions.get(key) or {}
        try:
            raw_score = int(round(float(item.get("score") or 0)))
        except (TypeError, ValueError):
            raw_score = 0
        value = max(0, min(maximum, raw_score))
        score += value
        dimensions[key] = {
            "score": value,
            "max_score": maximum,
            "rationale": str(item.get("rationale") or "未提供评分依据。"),
        }
    blockers = [str(item) for item in (data.get("blockers") or []) if str(item).strip()]
    issues = []
    for item in (data.get("issues") or [])[:30]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "minor").lower()
        if severity not in {"blocker", "major", "minor"}:
            severity = "minor"
        issues.append(
            {
                "severity": severity,
                "excerpt": str(item.get("excerpt") or "")[:300],
                "explanation": str(item.get("explanation") or ""),
                "suggestion": str(item.get("suggestion") or "")[:600],
            }
        )
    if any(item["severity"] == "blocker" for item in issues):
        blockers.append("问题清单中存在 blocker。")
    recurring_major = sum(item["severity"] == "major" for item in issues) >= 3
    if score < 75:
        decision = "rewrite"
    elif score < 85 or blockers or recurring_major:
        decision = "revise"
    else:
        decision = "native-ready"
    return {
        "target_locale": locale,
        "score": score,
        "decision": decision,
        "dimensions": dimensions,
        "blockers": list(dict.fromkeys(blockers)),
        "issues": issues,
        "strengths": [str(item) for item in (data.get("strengths") or [])[:10]],
        "revision_priorities": [
            str(item) for item in (data.get("revision_priorities") or [])[:10]
        ],
        "human_review_recommended": bool(
            data.get("human_review_recommended", True)
        ),
    }


def _progress(
    callback: Callable[[str, int, str], None] | None,
    stage: str,
    step: int,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, step, message)
