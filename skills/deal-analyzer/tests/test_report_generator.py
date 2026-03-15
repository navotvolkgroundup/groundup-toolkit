"""Tests for modules/report_generator.py — HTML conversion and report formatting."""

from modules.report_generator import (
    html_escape, markdown_to_html, format_whatsapp_summary,
    format_hubspot_note, format_email_with_link,
)


# ---------------------------------------------------------------------------
# html_escape()
# ---------------------------------------------------------------------------

def test_escape_ampersand():
    assert html_escape('A & B') == 'A &amp; B'

def test_escape_angle_brackets():
    assert html_escape('<script>') == '&lt;script&gt;'

def test_escape_quotes():
    assert html_escape('He said "hi"') == 'He said &quot;hi&quot;'

def test_escape_all_chars():
    assert html_escape('<a href="x">&') == '&lt;a href=&quot;x&quot;&gt;&amp;'

def test_escape_empty():
    assert html_escape('') == ''

def test_escape_no_special():
    assert html_escape('Hello World') == 'Hello World'


# ---------------------------------------------------------------------------
# markdown_to_html()
# ---------------------------------------------------------------------------

def test_md_h1():
    result = markdown_to_html('# Title')
    assert '<h1>Title</h1>' in result

def test_md_h2():
    result = markdown_to_html('## Subtitle')
    assert '<h2>Subtitle</h2>' in result

def test_md_h3():
    result = markdown_to_html('### Section')
    assert '<h3>Section</h3>' in result

def test_md_bold():
    result = markdown_to_html('This is **bold** text')
    assert '<strong>bold</strong>' in result

def test_md_inline_code():
    result = markdown_to_html('Use `print()` here')
    assert '<code>print()</code>' in result

def test_md_unordered_list():
    result = markdown_to_html('- Item 1\n- Item 2')
    assert '<ul>' in result
    assert '<li>Item 1</li>' in result
    assert '<li>Item 2</li>' in result
    assert '</ul>' in result

def test_md_ordered_list():
    result = markdown_to_html('1. First\n2. Second')
    assert '<ol>' in result
    assert '<li>First</li>' in result

def test_md_blockquote():
    result = markdown_to_html('> Important note')
    assert '<blockquote>' in result

def test_md_horizontal_rule():
    result = markdown_to_html('---')
    assert '<hr>' in result

def test_md_empty():
    assert markdown_to_html('') == ''
    assert markdown_to_html(None) == ''

def test_md_paragraph():
    result = markdown_to_html('Just a paragraph.')
    assert '<p>Just a paragraph.</p>' in result

def test_md_escapes_html_in_headers():
    result = markdown_to_html('# Title with <script>')
    assert '&lt;script&gt;' in result
    assert '<script>' not in result


# ---------------------------------------------------------------------------
# format_whatsapp_summary()
# ---------------------------------------------------------------------------

def test_whatsapp_with_url(sample_deck_data, sample_section_results):
    text = format_whatsapp_summary(sample_deck_data, sample_section_results, doc_url='https://docs.google.com/d/123')
    assert 'Acme AI' in text
    assert 'TL;DR:' in text
    assert 'docs.google.com' in text

def test_whatsapp_without_url(sample_deck_data, sample_section_results):
    text = format_whatsapp_summary(sample_deck_data, sample_section_results)
    assert 'sent to your email' in text

def test_whatsapp_truncates_long_memo(sample_deck_data):
    results = {
        'tldr': 'Short summary',
        'investment_memo': 'A' * 5000,
    }
    text = format_whatsapp_summary(sample_deck_data, results)
    assert len(text) < 5000


# ---------------------------------------------------------------------------
# format_hubspot_note()
# ---------------------------------------------------------------------------

def test_hubspot_with_url(sample_deck_data, sample_section_results):
    text = format_hubspot_note(sample_deck_data, sample_section_results, doc_url='https://docs.google.com/d/123')
    assert 'DEAL EVALUATION' in text
    assert 'Acme AI' in text
    assert 'docs.google.com' in text

def test_hubspot_without_url(sample_deck_data, sample_section_results):
    text = format_hubspot_note(sample_deck_data, sample_section_results)
    assert 'DEAL EVALUATION' in text
    assert 'Full report' not in text

def test_hubspot_truncates_long_memo(sample_deck_data):
    results = {
        'tldr': 'Quick summary',
        'investment_memo': 'B' * 5000,
    }
    text = format_hubspot_note(sample_deck_data, results)
    assert '[Full 12-section analysis' in text

def test_hubspot_short_memo(sample_deck_data):
    results = {
        'tldr': 'Quick',
        'investment_memo': 'Short memo.',
    }
    text = format_hubspot_note(sample_deck_data, results)
    assert '[Full 12-section' not in text


# ---------------------------------------------------------------------------
# format_email_with_link()
# ---------------------------------------------------------------------------

def test_email_format(sample_deck_data, sample_section_results):
    text = format_email_with_link(sample_deck_data, sample_section_results, 'https://docs.google.com/d/123')
    assert 'Acme AI' in text
    assert 'TL;DR' in text
    assert 'docs.google.com' in text
    assert 'due diligence' in text

def test_email_unknown_company():
    text = format_email_with_link({}, {'tldr': 'Test'}, 'https://example.com')
    assert 'Unknown Company' in text
