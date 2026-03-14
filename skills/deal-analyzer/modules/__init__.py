"""Deal Analyzer modules — modular pipeline components."""

from .deck_extractor import (
    extract_deck_links,
    fetch_deck_content,
    extract_deck_data,
    format_deck_data_text,
)

from .market_researcher import (
    build_research_queries,
    run_research,
    format_research_for_section,
)

from .section_analyzer import (
    SYSTEM_PROMPT,
    ANALYSIS_SECTIONS,
    SYNTHESIS_SECTION,
    run_section,
    run_analysis,
)

from .report_generator import (
    html_escape,
    markdown_to_html,
    format_report_html,
    create_google_doc,
    format_full_report,
    format_whatsapp_summary,
    format_hubspot_note,
    format_email_with_link,
    deliver_results,
)
