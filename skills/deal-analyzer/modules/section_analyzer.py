"""Phase 3: Claude-based section analysis, scoring."""

import sys
import time

from lib.whatsapp import send_whatsapp

from .deck_extractor import format_deck_data_text
from .market_researcher import format_research_for_section


SYSTEM_PROMPT = """You are a senior investment analyst combining expertise from Sequoia Capital, Andreessen Horowitz, Benchmark Capital, Accel, First Round Capital, Lightspeed Venture Partners, Insight Partners, Kleiner Perkins, GGV Capital, Tiger Global, Bessemer Venture Partners, and Index Ventures.

Your analysis must be:
- Grounded in the data provided (deck content and web research)
- Honest about gaps — explicitly state "Not available from deck — request from founders" rather than speculating or hallucinating data
- Quantitative where possible — use specific numbers, percentages, multiples, dollar figures
- Balanced — identify both strengths and risks for each section
- Actionable — end each section with 2-3 specific questions to ask the founders

When research data is provided, reference specific findings. When making estimates, clearly label them as estimates and state your confidence level (High/Medium/Low).

Format your output in clean markdown with headers, bullet points, and bold for key figures."""


ANALYSIS_SECTIONS = [
    {
        'id': 'market_sizing',
        'title': '1. Market Sizing & TAM Analysis',
        'relevant_research': ['market_size', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Analyze the market opportunity for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

MARKET RESEARCH:
{research_data}

Provide a complete market sizing analysis:

## 1. Market Sizing & TAM Analysis

- **Total Addressable Market (TAM)**: Global market size with data sources and methodology
- **Serviceable Available Market (SAM)**: Realistic portion this startup can reach given geography, go-to-market, and product scope
- **Serviceable Obtainable Market (SOM)**: What they can capture in 3-5 years with current trajectory
- **Market growth rate**: CAGR for next 5 years with key trend drivers
- **Market segments**: Break TAM into customer types or use cases with sizing per segment
- **Bottom-up validation**: Unit economics x potential customers calculation
- **Comparable markets**: Similar industries that scaled and their trajectory
- **Red flags**: Reasons market might be smaller than claimed

End with: Is this a venture-scale market? (Yes/No) Confidence: (High/Medium/Low)
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'competitive_landscape',
        'title': '2. Competitive Landscape Analysis',
        'relevant_research': ['competitors', 'company_news', 'company_linkedin'],
        'max_tokens': 1500,
        'prompt': """Analyze the competitive landscape for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

COMPETITIVE RESEARCH:
{research_data}

Provide a complete competitive analysis:

## 2. Competitive Landscape Analysis

- **Direct competitors**: Top 5 companies solving the same problem — name, funding, stage, differentiation
- **Indirect competitors**: 5 adjacent solutions customers currently use
- **Competitive positioning**: Where {company_name} fits (price vs. features matrix)
- **Moat analysis**: What makes each competitor defensible (network effects, switching costs, data, brand, IP)
- **White space**: Gaps no competitor is filling that {company_name} could own
- **Threat level**: Rate each competitor as Low/Medium/High threat with reasoning
- **Market share estimates**: Current distribution if data available
- **Strategic moves**: Recent funding, acquisitions, pivots, or partnerships by competitors

Format as competitive intelligence brief with comparison matrix.
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'founder_background',
        'title': '3. Founder Background Check',
        'relevant_research': ['founder_linkedin', 'founder_experience', 'founder_education', 'founder_linkedin_2', 'founder_experience_2', 'founder_linkedin_3', 'founder_experience_3', 'company_news'],
        'max_tokens': 1500,
        'prompt': """Evaluate the founding team of {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

FOUNDER RESEARCH:
{research_data}

Provide a founder diligence assessment:

## 3. Founder Background Check

- **Professional background**: Previous companies, roles, outcomes for each founder
- **Domain expertise**: Years in industry, specific achievements, unfair insights
- **Technical capabilities**: Engineering/product skills and ability to build v1
- **Network strength**: Key relationships, advisors, investors, industry connections
- **Previous ventures**: Track record — exits, failures, learnings
- **Team dynamics**: Complementary skills, how long working together, how they met
- **Red flags**: Gaps in experience, concerning patterns, missing roles
- **Commitment level**: Full-time status, financial skin in game

Format as founder diligence memo.
Risk assessment: (Low/Medium/High) with reasoning
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'unit_economics',
        'title': '4. Unit Economics Deep Dive',
        'relevant_research': ['unit_economics', 'market_size'],
        'max_tokens': 1500,
        'prompt': """Analyze the unit economics for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

BENCHMARK RESEARCH:
{research_data}

Provide a unit economics deep dive:

## 4. Unit Economics Deep Dive

- **Customer Acquisition Cost (CAC)**: Estimate from available data or industry benchmarks
- **Lifetime Value (LTV)**: Average revenue per customer x retention period
- **LTV:CAC ratio**: Target 3:1 minimum — how does this compare?
- **Payback period**: Months to recover CAC (target <12 months)
- **Gross margin**: Revenue minus COGS as percentage
- **Contribution margin**: After all variable costs per customer
- **Burn multiple**: Net burn / net new ARR (lower is better, target <2x)
- **Path to profitability**: When unit economics turn positive at scale

Where data is missing from the deck, provide industry benchmarks for comparison and clearly label estimates.

Format as financial analysis with sensitivity analysis (optimistic/base/pessimistic).
Questions for founders: (2-3 specific questions about their actual numbers)""",
    },
    {
        'id': 'product_market_fit',
        'title': '5. Product-Market Fit Assessment',
        'relevant_research': ['competitors', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Assess product-market fit for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

MARKET RESEARCH:
{research_data}

Provide a PMF assessment:

## 5. Product-Market Fit Assessment

- **Sean Ellis test**: Would 40%+ of users be "very disappointed" if the product disappeared? Evidence?
- **Retention signals**: Do cohorts flatten or decay? What does the deck suggest?
- **NPS indicators**: Any Net Promoter Score data or customer satisfaction signals
- **Organic growth**: What % of growth is organic/referral vs. paid acquisition
- **Usage frequency**: DAU/WAU/MAU ratios if available — how often do users engage?
- **Feature adoption**: Which features drive retention vs. vanity metrics
- **Customer testimonials**: Qualitative evidence of value delivered
- **Market pull signals**: Inbound demand, waitlist, word-of-mouth indicators

Based on available evidence, assess PMF status.

**PMF Verdict**: Pre-PMF / Emerging PMF / Strong PMF
**Confidence**: High/Medium/Low
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'traction_growth',
        'title': '6. Traction & Growth Metrics',
        'relevant_research': ['company_news', 'unit_economics'],
        'max_tokens': 1500,
        'prompt': """Analyze traction and growth for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

GROWTH RESEARCH:
{research_data}

Provide a traction analysis:

## 6. Traction & Growth Metrics Analysis

- **Revenue growth**: MoM and YoY growth rates if available
- **User growth**: New user acquisition rate and trajectory
- **Retention analysis**: Churn rates, cohort retention patterns
- **Sales efficiency**: Magic number (net new ARR / S&M spend) if calculable
- **Growth channels**: What channels work, estimated CAC by channel
- **Viral coefficient**: Does each user bring more users? Evidence?
- **Market penetration**: % of TAM/SAM captured so far
- **Leading indicators**: Signals that predict future growth acceleration or deceleration

Format as growth dashboard with trend analysis.
Growth trajectory: Accelerating / Steady / Decelerating / Too early to tell
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'financial_model',
        'title': '7. Financial Model Review',
        'relevant_research': ['unit_economics', 'comparable_exits'],
        'max_tokens': 1500,
        'prompt': """Review the financial model for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

BENCHMARK RESEARCH:
{research_data}

Provide a financial model assessment:

## 7. Financial Model Review

- **Revenue projections**: Are forecasts realistic vs. comparable companies at same stage?
- **Cost structure**: Fixed vs. variable costs breakdown and scalability
- **Burn rate**: Monthly cash consumption and implied runway
- **Capital efficiency**: Growth generated per dollar invested
- **Break-even analysis**: Revenue needed to reach profitability
- **Assumptions check**: Are growth rates, pricing, and margins reasonable?
- **Scenario modeling**: Best case / base case / worst case 3-year outcomes
- **Funding needs**: Capital required to reach next milestones and what those milestones are

Where specific financials aren't in the deck, note what's missing and provide comparable benchmarks.

Format as financial review with clearly stated assumptions.
Financial health: Strong / Adequate / Concerning / Insufficient data
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'technology_ip',
        'title': '8. Technology & IP Assessment',
        'relevant_research': ['competitors', 'industry_trends'],
        'max_tokens': 1500,
        'prompt': """Assess the technology and IP position of {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

TECHNOLOGY RESEARCH:
{research_data}

Provide a technical diligence assessment:

## 8. Technology & IP Assessment

- **Technology stack**: What they've built on and scalability implications
- **Proprietary technology**: What's unique vs. off-the-shelf components
- **IP portfolio**: Patents, trade secrets, proprietary algorithms, defensibility
- **Technical debt indicators**: Signals about engineering quality and practices
- **Data moat**: Proprietary data assets that strengthen over time with usage
- **Switching costs**: How hard is it for customers to leave once integrated?
- **Technical risks**: Dependencies, security considerations, scaling challenges
- **Team capability**: Can this team execute on the technical roadmap?

Format as technical diligence report.
Technical defensibility: Strong / Moderate / Weak / Insufficient data
Questions for founders: (2-3 specific technical questions)""",
    },
    {
        'id': 'gtm_strategy',
        'title': '9. Go-to-Market Strategy Evaluation',
        'relevant_research': ['competitors', 'market_size'],
        'max_tokens': 1500,
        'prompt': """Evaluate the go-to-market strategy for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

GTM RESEARCH:
{research_data}

Provide a GTM strategy evaluation:

## 9. Go-to-Market Strategy Evaluation

- **Customer acquisition**: What channels work and estimated CAC by channel
- **Sales model**: Self-serve, inside sales, field sales, or hybrid approach
- **Sales cycle**: Expected length and key friction points
- **Pricing strategy**: How they monetize, pricing tiers, competitive positioning on price
- **Channel partnerships**: Distribution deals, ecosystem plays, integrations
- **Marketing playbook**: What campaigns/content/events drive pipeline
- **Sales team**: Current size, productivity signals, quota attainment
- **GTM efficiency**: Sales & marketing spend as % of revenue vs. benchmarks

Format as GTM strategy review with optimization recommendations.
GTM readiness: Strong / Developing / Early / Needs rethinking
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'market_timing',
        'title': '10. Market Timing & Trend Analysis',
        'relevant_research': ['industry_trends', 'investor_landscape'],
        'max_tokens': 1500,
        'prompt': """Analyze market timing for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

TREND RESEARCH:
{research_data}

Provide a market timing analysis:

## 10. Market Timing & Trend Analysis

- **Market catalysts**: What changed recently that makes this possible now?
- **Technology enablers**: New tech that enables or improves this solution
- **Regulatory tailwinds/headwinds**: Policy changes creating opportunity or risk
- **Behavioral shifts**: Consumer/business behavior changes driving adoption
- **Why now**: Why couldn't this succeed 5 years ago? What's different?
- **Timing risks**: Is the market ready, or is this too early/too late?
- **Macro trends**: Economic, demographic, technological shifts helping or hurting
- **Competitive timing**: How long until copycats or incumbents respond?

Format as market timing memo.
Timing verdict: Perfect timing / Good timing / Slightly early / Slightly late / Wrong timing
Conviction level: High/Medium/Low
Questions for founders: (2-3 specific questions)""",
    },
    {
        'id': 'exit_scenarios',
        'title': '11. Exit Scenario & Return Analysis',
        'relevant_research': ['comparable_exits', 'investor_landscape'],
        'max_tokens': 1500,
        'prompt': """Analyze exit scenarios for {company_name}.

COMPANY DATA (from pitch deck):
{deck_data}

EXIT RESEARCH:
{research_data}

Provide exit scenario and return analysis:

## 11. Exit Scenario & Return Analysis

- **Potential acquirers**: 10 companies that could acquire this startup and why
- **Strategic rationale**: Why each acquirer would want this asset
- **Comparable exits**: Similar companies acquired in the space — deal size and multiples
- **IPO potential**: Is this a venture-scale outcome? Could it reach $1B+ valuation?
- **Timeline to exit**: Realistic years to liquidity event (3/5/7 year scenarios)
- **Return scenarios**: At current valuation, what ownership and exit price needed for target returns
- **Exit multiples**: Revenue and EBITDA multiples for comparable exits in this space
- **Liquidation preference impact**: How deal structure affects investor returns at various exit prices

Format as return analysis with probability-weighted scenarios.
Exit attractiveness: Highly attractive / Attractive / Moderate / Challenging
Questions for founders: (2-3 specific questions)""",
    },
]

# Section 12 is the synthesis — runs after sections 1-11
SYNTHESIS_SECTION = {
    'id': 'investment_memo',
    'title': '12. Investment Memo Summary',
    'max_tokens': 2500,
    'prompt': """You have completed a comprehensive 11-section investment analysis for {company_name}. Below are all findings.

COMPANY DATA (from pitch deck):
{deck_data}

COMPLETE ANALYSIS:
{prior_analysis}

Now write the final investment memo summary that synthesizes everything:

## 12. Investment Memo Summary

### Executive Summary
3 paragraphs: (1) The problem and market opportunity, (2) The solution and why this team, (3) Why now and the investment case

### Investment Recommendation
**Recommendation**: STRONG PASS / PASS / MONITOR / INVEST / STRONG INVEST
**Conviction Level**: Low / Medium / High
**Rationale**: 2-3 sentences explaining the recommendation

### Investment Thesis (if recommending INVEST)
5 reasons this could be a $1B+ company (or explain why it can't reach that scale)

### Key Strengths (Top 5)
Ranked by importance with evidence from the analysis

### Key Risks (Top 5)
Ranked by severity with mitigation strategies

### Deal Terms Assessment
Comment on valuation, round size, and terms relative to stage and traction

### Required Milestones for Next Round
What needs to happen in 12-18 months to raise the next round at 3-5x step-up

### Critical Questions Before Proceeding
Top 5 questions that must be answered before making an investment decision

### Comparable Companies
3-5 companies at similar stage that went on to succeed or fail, and what this implies""",
}


def run_section(section, deck_data, research_results):
    """Run a single analysis section through Claude Sonnet."""
    from analyzer import _call_claude_with_retry

    company = deck_data.get('company_name') or 'Unknown Company'
    deck_text = format_deck_data_text(deck_data)
    research_text = format_research_for_section(research_results, section.get('relevant_research', []))

    prompt = section['prompt'].format(
        company_name=company,
        deck_data=deck_text,
        research_data=research_text,
    )

    return _call_claude_with_retry(prompt, system_prompt=SYSTEM_PROMPT, max_tokens=section['max_tokens'])


def run_analysis(deck_data, research_results, progress_phone=None):
    """Phase 3: Run sections 1-11 sequentially (API rate limit: 5 RPM), then section 12 as synthesis."""
    from analyzer import _call_claude_with_retry

    section_results = {}

    # Run sections 1-11 sequentially to respect API rate limits
    for i, section in enumerate(ANALYSIS_SECTIONS):
        try:
            result = run_section(section, deck_data, research_results)
            section_results[section['id']] = result
            print(f"    [{i+1}/11] {section['title']}")
        except Exception as e:
            section_results[section['id']] = f"Analysis failed: {e}"
            print(f"    [{i+1}/11] FAILED: {section['title']}: {e}", file=sys.stderr)

        # Send progress update at milestones
        if progress_phone and i in (3, 7):
            milestone = "Market, competition, team, and economics done..." if i == 3 else "Almost there — finalizing strategy and exit analysis..."
            send_whatsapp(progress_phone, milestone)

        # Small delay between calls to stay under rate limit
        if i < len(ANALYSIS_SECTIONS) - 1:
            time.sleep(2)

    # Run synthesis (section 12) with all prior results
    print("    Running synthesis...")
    company = deck_data.get('company_name') or 'Unknown Company'
    deck_text = format_deck_data_text(deck_data)

    prior_analysis = '\n\n---\n\n'.join(
        f"{s['title']}\n\n{section_results.get(s['id'], 'Analysis not available')}"
        for s in ANALYSIS_SECTIONS
    )

    synthesis_prompt = SYNTHESIS_SECTION['prompt'].format(
        company_name=company,
        deck_data=deck_text,
        prior_analysis=prior_analysis,
    )

    section_results['investment_memo'] = _call_claude_with_retry(
        synthesis_prompt, system_prompt=SYSTEM_PROMPT, max_tokens=SYNTHESIS_SECTION['max_tokens']
    )
    print("    Done: 12. Investment Memo Summary")

    # Generate TL;DR
    print("    Generating TL;DR...")
    tldr_prompt = f"""Write a single TL;DR paragraph (3-5 sentences) summarizing this investment evaluation. Include: what the company does, key traction numbers, the recommendation (invest/pass/monitor), and the top reason for that recommendation.

INVESTMENT MEMO:
{section_results['investment_memo'][:3000]}

Write ONLY the paragraph, no label or prefix."""

    section_results['tldr'] = _call_claude_with_retry(tldr_prompt, model="claude-haiku-4-5-20251001", max_tokens=300)
    print("    Done: TL;DR")

    return section_results
