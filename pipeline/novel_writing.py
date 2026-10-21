from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings
from analyzer.english_fiction_quality import (
    render_review_markdown,
    review_english_fiction,
)
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
    run_cancellable_call,
)
from infrastructure.progress import TextProgressMessage
from integrations.local_skills import load_novel_writing_skill


NOVEL_OPERATIONS = {
    "concept": "故事设定",
    "outline": "长篇大纲",
    "chapter": "章节创作",
    "continue": "续写",
    "rewrite": "改写",
    "diagnose": "诊断",
    "revise": "修订",
}
SOURCE_REQUIRED_OPERATIONS = {"continue", "rewrite", "diagnose", "revise"}
OUTPUT_LANGUAGES = {
    "zh-CN": {
        "label": "简体中文",
        "unit": "字",
    },
    "en-US": {
        "label": "English (US)",
        "unit": "words",
    },
    "en-GB": {
        "label": "English (UK)",
        "unit": "words",
    },
}


def run_novel_writing(
    request: str,
    settings: Settings,
    *,
    operation: str = "chapter",
    output_language: str = "zh-CN",
    source_text: str = "",
    target_length: int = 3000,
    use_corpus_observations: bool = False,
    native_english_review: bool = True,
    auto_native_revision: bool = True,
    progress_callback: Callable[[str, int, str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    request = str(request or "").strip()
    source_text = str(source_text or "").strip()
    operation = str(operation or "chapter").strip().lower()
    output_language = str(output_language or "zh-CN").strip()
    if not request:
        raise ValueError("请输入小说创作要求。")
    if operation not in NOVEL_OPERATIONS:
        raise ValueError(f"不支持的小说操作：{operation}")
    if output_language not in OUTPUT_LANGUAGES:
        raise ValueError(f"不支持的输出语言：{output_language}")
    if operation in SOURCE_REQUIRED_OPERATIONS and not source_text:
        raise ValueError(f"{NOVEL_OPERATIONS[operation]}需要提供原文。")
    if not settings.llm_api_key:
        raise RuntimeError("尚未配置 LLM_API_KEY，无法执行小说创作。")
    target_length = max(300, min(20000, int(target_length or 3000)))
    length_unit = OUTPUT_LANGUAGES[output_language]["unit"]

    raise_if_cancelled(cancel_requested)
    _progress(progress_callback, "读取小说 Skill", 8, "正在读取本机 novel-writing。")
    skill = load_novel_writing_skill(
        settings.novel_writing_skill_path,
        include_corpus_observations=use_corpus_observations,
    )
    system_prompt = _build_system_prompt(skill)
    user_prompt = _build_user_prompt(
        operation,
        output_language,
        request,
        source_text,
        target_length,
        settings.llm_max_chars,
    )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 openai SDK，无法调用兼容模型接口。") from exc

    client_kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**client_kwargs)
    _progress(progress_callback, "小说创作", 15, "模型已连接，开始生成。")
    try:
        response = run_cancellable_call(
            lambda: client.chat.completions.create(
                model=settings.llm_model,
                temperature=0.75 if operation not in {"diagnose", "outline"} else 0.45,
                stream=True,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            cancel_requested,
            on_cancel=getattr(client, "close", None),
        )
        chunks: list[str] = []
        generated_units = 0
        last_update_units = 0
        last_update_at = time.monotonic()
        try:
            for chunk in response:
                raise_if_cancelled(cancel_requested)
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if not content:
                    continue
                text = str(content)
                chunks.append(text)
                generated_units = _measure_output("".join(chunks), output_language)
                now = time.monotonic()
                update_threshold = 120 if output_language == "zh-CN" else 40
                if generated_units - last_update_units >= update_threshold or now - last_update_at >= 1:
                    ratio = min(1.0, generated_units / max(target_length, 1))
                    _progress(
                        progress_callback,
                        "小说创作",
                        min(90, 18 + int(ratio * 72)),
                        TextProgressMessage(
                            f"正在生成：{generated_units}/{target_length} {length_unit}",
                            generated_units=generated_units,
                            target_units=target_length,
                            unit_label=length_unit,
                        ),
                    )
                    last_update_units = generated_units
                    last_update_at = now
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        raise_if_cancelled(cancel_requested)
        output = "".join(chunks).strip()
        if not output:
            raise RuntimeError("模型没有返回小说内容。")
    except JobCancelledError:
        raise
    finally:
        close_client = getattr(client, "close", None)
        if callable(close_client):
            close_client()

    review_result: dict[str, Any] | None = None
    review_error: str | None = None
    draft_output = output
    if output_language.startswith("en-") and native_english_review:
        try:
            review_result = review_english_fiction(
                output,
                settings,
                locale=output_language,
                auto_revise=auto_native_revision,
                progress_callback=lambda stage, step, message: _progress(
                    progress_callback,
                    stage,
                    min(96, 90 + int(step)),
                    message,
                ),
                cancel_requested=cancel_requested,
            )
            output = str(review_result["final_text"]).strip()
        except JobCancelledError:
            raise
        except Exception as exc:
            review_error = str(exc)

    _progress(progress_callback, "保存小说", 97, "正在保存成品、质检报告和创作记录。")
    output_dir = _make_output_dir(settings.novel_writing_output_dir)
    result_path = output_dir / "result.md"
    record_path = output_dir / "request.json"
    _atomic_write_text(result_path, output + "\n")
    original_draft_path: Path | None = None
    review_json_path: Path | None = None
    review_markdown_path: Path | None = None
    review_summary: dict[str, Any] | None = None
    if review_result is not None:
        if review_result["revised"]:
            original_draft_path = output_dir / "original_draft.md"
            _atomic_write_text(original_draft_path, draft_output + "\n")
        review_payload = {
            key: value
            for key, value in review_result.items()
            if key not in {"original_text", "final_text"}
        }
        review_json_path = output_dir / "native_review.json"
        review_markdown_path = output_dir / "native_review.md"
        _atomic_write_text(
            review_json_path,
            json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write_text(
            review_markdown_path,
            render_review_markdown(review_result),
        )
        final_review = review_result["final"]["review"]
        review_summary = {
            "score": final_review["score"],
            "decision": final_review["decision"],
            "revised": review_result["revised"],
            "review_model": review_result["review_model"],
            "harper_available": review_result["final"]["deterministic"]["harper"]["available"],
            "readability_engine": review_result["final"]["deterministic"]["readability"].get(
                "engine",
                "builtin-readability-v2",
            ),
        }
    record = {
        "schema_version": "1.1",
        "created_at": datetime.now().astimezone().isoformat(),
        "operation": operation,
        "operation_label": NOVEL_OPERATIONS[operation],
        "output_language": output_language,
        "output_language_label": OUTPUT_LANGUAGES[output_language]["label"],
        "request": request,
        "source_chars": len(source_text),
        "target_length": target_length,
        "output_length": _measure_output(output, output_language),
        "length_unit": length_unit,
        "output_chars": len(output),
        "model": settings.llm_model,
        "skill": skill.status(),
        "used_corpus_observations": use_corpus_observations,
        "native_english_review_requested": bool(
            output_language.startswith("en-") and native_english_review
        ),
        "auto_native_revision": bool(auto_native_revision),
        "native_review": review_summary,
        "native_review_error": review_error,
    }
    _atomic_write_text(
        record_path,
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "operation": operation,
        "operation_label": NOVEL_OPERATIONS[operation],
        "output_language": output_language,
        "output_language_label": OUTPUT_LANGUAGES[output_language]["label"],
        "output_chars": len(output),
        "output_length": _measure_output(output, output_language),
        "target_length": target_length,
        "length_unit": length_unit,
        "result_path": result_path,
        "record_path": record_path,
        "skill": skill.status(),
        "native_review": review_summary,
        "native_review_error": review_error,
        "original_draft_path": original_draft_path,
        "review_json_path": review_json_path,
        "review_markdown_path": review_markdown_path,
    }


def _build_system_prompt(skill: Any) -> str:
    reference_blocks = "\n\n".join(
        f"## 参考资源：{name}\n{content}"
        for name, content in skill.references.items()
    )
    return (
        "你正在 ContentResearch 的本地小说工作流中执行任务。"
        "以下 novel-writing Skill 是最高优先级的创作规范；严格执行质量门槛、"
        "原创性和不模仿具体作者风格的约束。不要解释你读取了哪些文件，直接交付用户要求的产物。\n\n"
        f"# novel-writing Skill\n{skill.instructions}\n\n{reference_blocks}"
    )


def _build_user_prompt(
    operation: str,
    output_language: str,
    request: str,
    source_text: str,
    target_length: int,
    max_chars: int,
) -> str:
    source_budget = max(1000, int(max_chars) - len(request) - 8000)
    clipped_source = source_text[:source_budget]
    if output_language == "zh-CN":
        source_note = ""
        if source_text:
            source_note = (
                f"\n\n## 原文（{len(source_text)} 字"
                f"，本次提供 {len(clipped_source)} 字）\n{clipped_source}"
            )
        return (
            f"## 本次操作\n{NOVEL_OPERATIONS[operation]}\n\n"
            f"## 用户要求\n{request}\n\n"
            f"## 目标长度\n约 {target_length} 个中文字符。以完成叙事功能为先，允许合理浮动。"
            f"{source_note}\n\n"
            "只输出可直接使用的简体中文 Markdown 成品。使用自然、当代的中文小说表达，避免翻译腔。"
            "若用户信息不足，基于 Skill 的故事契约做最小合理假设，并在成品开头用“创作假设”"
            "简短列明；不要反问。"
        )

    locale_name = "American" if output_language == "en-US" else "British"
    operation_name = {
        "concept": "story concept",
        "outline": "long-form outline",
        "chapter": "chapter drafting",
        "continue": "continuation",
        "rewrite": "rewrite",
        "diagnose": "diagnosis",
        "revise": "revision",
    }[operation]
    source_note = ""
    if source_text:
        source_note = (
            f"\n\n## Source text ({len(source_text)} characters; "
            f"{len(clipped_source)} supplied)\n{clipped_source}"
        )
    return (
        f"## Task\n{operation_name}\n\n"
        f"## User brief\n{request}\n\n"
        f"## Target length\nApproximately {target_length} English words. Narrative completeness takes priority; "
        f"reasonable variation is allowed.{source_note}\n\n"
        f"Write the entire deliverable in idiomatic contemporary {locale_name} English at native publication quality. "
        "Retain Chinese web-serial craft mechanics—clear progression, frequent earned payoffs, escalating gates, "
        "relationship and mystery movement, and directional chapter hooks—but never translate Chinese syntax literally. "
        f"Use consistent {locale_name} spelling, natural dialogue, contractions where appropriate, and sentence rhythms "
        "that sound fluent when read aloud. Make culture-bound terms understandable through brief, unobtrusive context; "
        "avoid Chinglish, literal idioms, unexplained honorific repetition, and exposition that stops the scene. "
        "Output only ready-to-use English Markdown. If material information is missing, make the smallest reasonable "
        "story-contract assumptions and list them briefly under ‘Creative assumptions’; do not ask follow-up questions."
    )


def _measure_output(text: str, output_language: str) -> int:
    if output_language == "zh-CN":
        return len(text)
    return len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+", text))


def _progress(
    callback: Callable[[str, int, str], None] | None,
    stage: str,
    progress: int,
    message: str,
) -> None:
    if callback is not None:
        callback(stage, progress, message)


def _make_output_dir(root: Path) -> Path:
    name = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    path = Path(root) / name
    path.mkdir(parents=True, exist_ok=False)
    return path


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
