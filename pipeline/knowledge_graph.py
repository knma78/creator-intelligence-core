from __future__ import annotations

from typing import Any, Callable, TypedDict

from config import SETTINGS, Settings


class KnowledgeGraphState(TypedDict, total=False):
    lexical_index: str
    vector_manifest: str
    creator_manifest: str
    template_library: str
    gap_analysis: str
    discovery_dashboard: str
    project_report: str
    steps: list[str]
    warnings: list[str]


def run_advanced_knowledge_graph(
    settings: Settings = SETTINGS,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict[str, Any]:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("LangGraph is not installed. Install advanced requirements first.") from exc

    graph = StateGraph(KnowledgeGraphState)
    graph.add_node(
        "lexical",
        lambda state: _run_step(state, settings, progress_callback, "词法索引", 20, "正在整理视频文档和关键词索引。", _build_lexical),
    )
    graph.add_node(
        "vector",
        lambda state: _run_step(state, settings, progress_callback, "语义向量", 38, "正在用本地模型生成语义向量，这一步通常最耗时。", _build_vector),
    )
    graph.add_node(
        "creator",
        lambda state: _run_step(state, settings, progress_callback, "创作者知识库", 70, "正在更新创作者画像和模板库。", _build_creator),
    )
    graph.add_node(
        "gap",
        lambda state: _run_step(state, settings, progress_callback, "能力缺口", 84, "正在重新计算能力成熟度和缺口。", _build_gap),
    )
    graph.add_node(
        "discovery",
        lambda state: _run_step(state, settings, progress_callback, "创作者发现", 92, "正在生成平台、关键词和候选创作者计划。", _build_discovery),
    )
    graph.add_node(
        "project",
        lambda state: _run_step(state, settings, progress_callback, "项目报告", 97, "正在汇总完整项目报告。", _build_project),
    )
    graph.add_edge(START, "lexical")
    graph.add_edge("lexical", "vector")
    graph.add_edge("vector", "creator")
    graph.add_edge("creator", "gap")
    graph.add_edge("gap", "discovery")
    graph.add_edge("discovery", "project")
    graph.add_edge("project", END)
    return dict(graph.compile().invoke({"steps": [], "warnings": []}))


def _run_step(
    state: KnowledgeGraphState,
    settings: Settings,
    progress_callback: Callable[[str, int, str], None] | None,
    stage: str,
    percent: int,
    message: str,
    builder: Callable[[KnowledgeGraphState, Settings], KnowledgeGraphState],
) -> KnowledgeGraphState:
    if progress_callback:
        progress_callback(stage, percent, message)
    return builder(state, settings)


def _build_lexical(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from rag.knowledge_base import build_knowledge_base

    path = build_knowledge_base(
        settings.output_dir,
        settings.knowledge_base_dir / "index.json",
        settings,
    )
    return {"lexical_index": str(path), "steps": [*state.get("steps", []), "lexical"]}


def _build_vector(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from rag.vector_store import build_vector_knowledge_base

    try:
        path = build_vector_knowledge_base(settings=settings)
        return {"vector_manifest": str(path), "steps": [*state.get("steps", []), "vector"]}
    except Exception as exc:
        return {
            "steps": [*state.get("steps", []), "vector_skipped"],
            "warnings": [*state.get("warnings", []), f"向量知识库未更新：{exc}"],
        }


def _build_creator(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from exporter.creator_learning import build_creator_knowledge_base
    from exporter.integrated import integrate_outputs
    from exporter.template_library import build_template_library

    integrate_outputs(settings.output_dir, settings.cache_dir)
    creator = build_creator_knowledge_base(settings.output_dir, settings.cache_dir)
    templates = build_template_library(settings.output_dir, cache_root=settings.cache_dir)
    return {
        "creator_manifest": str(creator["manifest"]),
        "template_library": str(templates["template_library_json"]),
        "steps": [*state.get("steps", []), "creator"],
    }


def _build_gap(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from intelligence.gap_analysis.api import run_gap_analysis

    run_gap_analysis(settings=settings, save=True)
    path = settings.output_dir / "gap_analysis" / "latest.json"
    return {"gap_analysis": str(path), "steps": [*state.get("steps", []), "gap"]}


def _build_discovery(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from intelligence.creator_discovery.api import discover_creator

    discover_creator(settings=settings, save=True)
    path = settings.output_dir / "creator_discovery" / "dashboard.json"
    return {"discovery_dashboard": str(path), "steps": [*state.get("steps", []), "discovery"]}


def _build_project(state: KnowledgeGraphState, settings: Settings) -> KnowledgeGraphState:
    from exporter.project_report import build_project_information_report

    report = build_project_information_report(settings.output_dir)
    return {
        "project_report": str(report["json"]),
        "steps": [*state.get("steps", []), "project"],
    }
