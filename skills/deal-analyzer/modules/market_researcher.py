"""Phase 2: Brave search, market research, competitor analysis."""

import time

from lib.brave import brave_search


def build_research_queries(deck_data):
    company = deck_data.get('company_name') or ''
    industry = deck_data.get('industry') or ''
    founders = deck_data.get('founder_names') or []
    product = deck_data.get('product_overview') or ''
    target = deck_data.get('target_customers') or ''

    queries = {}

    if industry:
        queries['market_size'] = f"{industry} market size TAM 2025 2026"
        queries['industry_trends'] = f"{industry} trends growth drivers 2025 2026"
        queries['investor_landscape'] = f"{industry} VC investment funding rounds 2025"

    if company:
        queries['competitors'] = f"{company} competitors {industry} landscape".strip()
        queries['company_news'] = f"{company} startup funding news 2025 2026"

    if founders:
        # Search all founders (up to 3) with targeted queries
        for i, founder in enumerate(founders[:3]):
            suffix = f"_{i+1}" if i > 0 else ""
            queries[f'founder_linkedin{suffix}'] = f"{founder} site:linkedin.com/in"
            queries[f'founder_experience{suffix}'] = f"{founder} previous companies startups exits"
        queries['founder_education'] = f"{founders[0]} education university degree"

    if company:
        queries['company_linkedin'] = f"{company} site:linkedin.com/company"

    if industry:
        queries['comparable_exits'] = f"{industry} startup acquisitions exits M&A 2024 2025"
        bm = deck_data.get('business_model') or ''
        if 'saas' in bm.lower() or 'subscription' in bm.lower():
            queries['unit_economics'] = f"{industry} SaaS unit economics benchmarks LTV CAC"
        else:
            queries['unit_economics'] = f"{industry} startup benchmarks unit economics metrics"

    return queries


def run_research(queries):
    results = {}
    for qid, query in queries.items():
        print(f"    Searching: {query[:60]}...")
        results[qid] = brave_search(query, count=5)
        time.sleep(0.3)
    total = sum(len(v) for v in results.values())
    print(f"    Total: {total} results from {len(queries)} queries")
    return results


def format_research_for_section(research_results, relevant_keys):
    parts = []
    for key in relevant_keys:
        items = research_results.get(key, [])
        if not items:
            continue
        for item in items[:4]:
            parts.append(f"- {item['title']}: {item['description']}")
    if not parts:
        return "No relevant research data available."
    return '\n'.join(parts)
