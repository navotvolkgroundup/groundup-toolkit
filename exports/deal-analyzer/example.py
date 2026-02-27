"""
Example: Run the deal analyzer on a pitch deck.

Setup:
  pip install requests
  export ANTHROPIC_API_KEY="sk-..."
  export BRAVE_SEARCH_API_KEY="..."   # optional, for web research

Usage:
  python example.py https://docsend.com/view/abc123
  python example.py ./decks/startup.pdf
  python example.py --text "Company: Acme Corp..."
"""

import sys
import os
from deal_analyzer import DealAnalyzer


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    source = sys.argv[1]

    # Progress callback — prints status to console
    def on_progress(phase, step, total, message):
        bar = f"[{step}/{total}]"
        print(f"  {phase.upper()} {bar} {message}")

    # Initialize
    analyzer = DealAnalyzer(
        # API keys from env or pass directly:
        # anthropic_api_key="sk-...",
        # brave_search_api_key="...",

        # Customize branding:
        firm_name="My VC Fund",
        disclaimer="AI-generated analysis. Validate before investing.",

        # Progress updates:
        on_progress=on_progress,
    )

    # --- Option A: Full evaluation (extract + research + 12 sections) ---
    print(f"Evaluating: {source}\n")
    result = analyzer.evaluate(source)

    if not result:
        print("Failed to analyze deck. Check the URL/file and try again.")
        sys.exit(1)

    company = result["deck_data"].get("company_name", "Unknown")
    print(f"\n{'='*60}")
    print(f"  {company}")
    print(f"{'='*60}")
    print(f"\nTL;DR:\n{result['tldr']}")
    print(f"\nFull markdown report: {len(result['markdown_report'])} chars")
    print(f"Full HTML report:     {len(result['html_report'])} chars")

    # Save reports to files
    safe_name = company.lower().replace(' ', '-').replace('/', '-')
    with open(f"{safe_name}-report.html", "w") as f:
        f.write(result["html_report"])
    with open(f"{safe_name}-report.md", "w") as f:
        f.write(result["markdown_report"])
    print(f"\nSaved: {safe_name}-report.html, {safe_name}-report.md")

    # --- Option B: Step-by-step (if you want control over each phase) ---
    #
    # deck_data = analyzer.extract(source)
    # research = analyzer.research(deck_data)
    # sections = analyzer.analyze(deck_data, research)
    # # sections["tldr"], sections["investment_memo"], sections["market_sizing"], etc.


if __name__ == "__main__":
    main()
