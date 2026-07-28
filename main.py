from __future__ import annotations

import argparse
import json
import logging
from dataclasses import replace
from pathlib import Path

from config import SETTINGS, Settings, setup_logging
from downloader.bilibili import is_bilibili_url
from downloader.bilibili_up import is_bilibili_up_source
from downloader.social import detect_social_platform, is_douyin_profile_url
from downloader.youtube import is_youtube_channel_url, is_youtube_url
from pipeline.batch import run_up_pipeline
from pipeline.run import run_video_pipeline

logger = logging.getLogger(__name__)


def run_pipeline(source: str, settings: Settings = SETTINGS, enrich_v3: bool = False) -> Path:
    return run_video_pipeline(source, settings, enrich_v3=enrich_v3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Content Research Pipeline V1/V2/V3/V4")
    parser.add_argument(
        "source",
        nargs="?",
        help=(
            "Bilibili/YouTube/Douyin/Xiaohongshu video URL, BV id, "
            "Bilibili UP, YouTube channel or Douyin creator homepage, "
            "Bilibili mid, or local video path."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ignore existing cache and rerun download/transcription/analysis where possible.",
    )
    parser.add_argument(
        "--up",
        action="store_true",
        help="Treat source as a Bilibili/YouTube/Douyin creator homepage and run batch analysis.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max videos to analyze for UP batch mode.")
    parser.add_argument("--v3", action="store_true", help="Enable V3 enrichment: comments, cover, OCR, title stats.")
    parser.add_argument("--build-kb", action="store_true", help="Build the local RAG knowledge base after analysis, or by itself.")
    parser.add_argument("--build-vector-kb", action="store_true", help="Build the Chroma semantic vector knowledge base.")
    parser.add_argument("--semantic-search", help="Search only the Chroma semantic vector knowledge base.")
    parser.add_argument("--advanced-kb", action="store_true", help="Run the LangGraph advanced knowledge-base workflow.")
    parser.add_argument("--search", help="Search the local RAG knowledge base.")
    parser.add_argument("--report", help="Generate a V4 research report from the local knowledge base.")
    parser.add_argument("--build-creator-kb", action="store_true", help="Build the Creator Knowledge Base from local outputs.")
    parser.add_argument("--creator-search", help="Search the Creator Knowledge Base.")
    parser.add_argument("--build-template-library", action="store_true", help="Build reusable creator capability templates.")
    parser.add_argument("--creator-specs", default="", help="Optional creator specs JSON for author aliases and positioning.")
    parser.add_argument("--up-advisor", help="Ask which UP series should be crawled next for a target direction.")
    parser.add_argument("--gap-analysis", action="store_true", help="Run rule-first Knowledge Gap Analysis.")
    parser.add_argument("--gap-ability", help="Optional ability key/name for focused gap analysis.")
    parser.add_argument("--project-report", action="store_true", help="Build a project-level integrated information report.")
    parser.add_argument("--top-k", type=int, default=5, help="Search result count.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = replace(SETTINGS, overwrite_cache=args.overwrite)
    setup_logging(settings)
    logger.info("Starting Content Research Pipeline")
    try:
        if args.project_report and not args.source:
            from exporter.integrated import integrate_outputs
            from exporter.creator_learning import build_creator_knowledge_base
            from exporter.template_library import build_template_library
            from exporter.project_report import build_project_information_report

            integrate_outputs(settings.output_dir, settings.cache_dir)
            build_creator_knowledge_base(
                settings.output_dir,
                settings.cache_dir,
                creator_specs_path=Path(args.creator_specs) if args.creator_specs else None,
            )
            build_template_library(settings.output_dir, cache_root=settings.cache_dir)
            result = build_project_information_report(settings.output_dir)
            print(f"Project integration markdown: {result['markdown']}")
            print(f"Project integration JSON: {result['json']}")
            return

        if args.advanced_kb and not args.source:
            from pipeline.knowledge_graph import run_advanced_knowledge_graph

            result = run_advanced_knowledge_graph(settings)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        if args.up_advisor is not None and not args.source:
            from exporter.up_advisor import build_up_advisor_report

            result = build_up_advisor_report(args.up_advisor, settings.output_dir)
            print(f"UP advisor markdown: {result['markdown']}")
            print(f"UP advisor JSON: {result['json']}")
            return

        if (args.gap_analysis or args.gap_ability) and not args.source:
            from intelligence.gap_analysis.api import get_gap, run_gap_analysis

            if args.gap_ability:
                result = get_gap(args.gap_ability, settings=settings)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return
            result = run_gap_analysis(settings=settings, save=True)
            output_dir = settings.output_dir / "gap_analysis"
            print(f"Knowledge Gap Analysis: {output_dir / 'latest.json'}")
            print(f"Dashboard JSON: {output_dir / 'dashboard.json'}")
            print(
                f"Health: {result['knowledge_health']['overall_score']} "
                f"({result['knowledge_health']['status']})"
            )
            return

        if args.creator_search:
            from exporter.creator_learning import build_creator_knowledge_base, search_creator_knowledge_base
            from exporter.template_library import build_template_library

            index_path = settings.cache_dir / "creator_knowledge_base" / "index.json"
            if args.build_creator_kb or not index_path.exists():
                build_creator_knowledge_base(
                    settings.output_dir,
                    settings.cache_dir,
                    creator_specs_path=Path(args.creator_specs) if args.creator_specs else None,
                )
                build_template_library(settings.output_dir, cache_root=settings.cache_dir)
            results = search_creator_knowledge_base(args.creator_search, index_path=index_path, top_k=args.top_k)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return

        if args.build_creator_kb and not args.source:
            from exporter.creator_learning import build_creator_knowledge_base
            from exporter.template_library import build_template_library

            result = build_creator_knowledge_base(
                settings.output_dir,
                settings.cache_dir,
                creator_specs_path=Path(args.creator_specs) if args.creator_specs else None,
            )
            template_result = build_template_library(settings.output_dir, cache_root=settings.cache_dir)
            print(f"Creator KB manifest: {result['manifest']}")
            print(f"Creator KB markdown: {result['knowledge_markdown']}")
            print(f"Creator RAG index: {result['rag_index']}")
            print(f"Template library: {template_result['template_library_markdown']}")
            print(f"Template RAG index: {template_result['template_rag_index']}")
            return

        if args.build_template_library and not args.source:
            from exporter.template_library import build_template_library

            result = build_template_library(settings.output_dir, cache_root=settings.cache_dir)
            print(f"Template library: {result['template_library_markdown']}")
            print(f"Template JSON: {result['template_library_json']}")
            print(f"Template RAG index: {result['template_rag_index']}")
            return

        if args.report:
            from rag.report import generate_research_report

            result = generate_research_report(
                args.report,
                settings=settings,
                top_k=args.top_k,
                rebuild_kb=args.build_kb,
            )
            print(f"V4 report: {result['markdown_path']}")
            print(f"Report JSON: {result['json_path']}")
            return

        if args.search:
            from rag.knowledge_base import search_knowledge_base

            results = search_knowledge_base(args.search, top_k=args.top_k, settings=settings)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return

        if args.semantic_search:
            from rag.vector_store import search_vector_knowledge_base

            results = search_vector_knowledge_base(args.semantic_search, top_k=args.top_k, settings=settings)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return

        if args.build_vector_kb and not args.source:
            from rag.knowledge_base import build_knowledge_base
            from rag.vector_store import build_vector_knowledge_base

            lexical_path = settings.knowledge_base_dir / "index.json"
            if not lexical_path.exists():
                build_knowledge_base(settings.output_dir, lexical_path, settings)
            manifest_path = build_vector_knowledge_base(lexical_path, settings)
            print(f"Vector knowledge base built: {manifest_path}")
            return

        if args.build_kb and not args.source:
            from rag.knowledge_base import build_knowledge_base

            kb_path = build_knowledge_base(settings.output_dir, settings.knowledge_base_dir / "index.json", settings)
            print(f"Knowledge base built: {kb_path}")
            return

        if not args.source:
            raise SystemExit("Missing source. Provide a video link/BV/local file, use --up for UP batch, or use --search/--build-kb.")

        source_path_exists = Path(args.source).expanduser().exists()
        should_run_up = (
            args.up
            or is_bilibili_up_source(args.source)
            or is_youtube_channel_url(args.source)
            or is_douyin_profile_url(args.source)
            or (
                not is_bilibili_url(args.source)
                and not is_youtube_url(args.source)
                and not detect_social_platform(args.source)
                and not source_path_exists
                and "://" not in args.source
            )
        )
        if should_run_up:
            result = run_up_pipeline(
                args.source,
                settings,
                limit=args.limit,
                enrich_v3=args.v3,
                build_kb=args.build_kb or args.build_vector_kb,
            )
            print(f"UP profile: {result['profile_path']}")
            print(f"Batch manifest: {result['manifest_path']}")
            if result.get("knowledge_base_path"):
                print(f"Knowledge base: {result['knowledge_base_path']}")
            if args.build_vector_kb:
                from rag.vector_store import build_vector_knowledge_base

                manifest_path = build_vector_knowledge_base(settings=settings)
                print(f"Vector knowledge base built: {manifest_path}")
            return

        markdown_path = run_pipeline(args.source, settings, enrich_v3=args.v3)
        print(f"Done: {markdown_path}")
        if args.build_kb or args.build_vector_kb:
            from rag.knowledge_base import build_knowledge_base

            kb_path = build_knowledge_base(settings.output_dir, settings.knowledge_base_dir / "index.json", settings)
            print(f"Knowledge base built: {kb_path}")
        if args.build_vector_kb:
            from rag.vector_store import build_vector_knowledge_base

            manifest_path = build_vector_knowledge_base(settings=settings)
            print(f"Vector knowledge base built: {manifest_path}")
    except Exception:
        logger.exception("Pipeline failed")
        raise


if __name__ == "__main__":
    main()
