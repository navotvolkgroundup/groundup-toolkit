"""Tests for modules/deck_extractor.py — deck link extraction and formatting."""

from modules.deck_extractor import extract_deck_links, format_deck_data_text


# ---------------------------------------------------------------------------
# extract_deck_links()
# ---------------------------------------------------------------------------

def test_extract_docsend():
    text = 'Check our deck at https://docsend.com/view/abc123xyz'
    links = extract_deck_links(text)
    assert len(links) == 1
    assert links[0] == 'https://docsend.com/view/abc123xyz'

def test_extract_gdocs():
    text = 'Deck: https://docs.google.com/presentation/d/abc123/edit'
    links = extract_deck_links(text)
    assert len(links) == 1
    assert 'docs.google.com' in links[0]

def test_extract_gdrive():
    text = 'https://drive.google.com/file/d/abc123/view'
    links = extract_deck_links(text)
    assert len(links) == 1

def test_extract_dropbox():
    text = 'https://www.dropbox.com/s/abc123/deck.pdf?dl=0'
    links = extract_deck_links(text)
    assert len(links) == 1

def test_extract_papermark():
    text = 'https://papermark.com/view/deck-abc123'
    links = extract_deck_links(text)
    assert len(links) == 1

def test_extract_pitch():
    text = 'https://pitch.com/public/abc-123'
    links = extract_deck_links(text)
    assert len(links) == 1

def test_extract_multiple():
    text = '''Here are links:
https://docsend.com/view/abc
https://docs.google.com/presentation/d/xyz/edit
https://drive.google.com/file/d/123/view'''
    links = extract_deck_links(text)
    assert len(links) == 3

def test_extract_deduplicates():
    text = '''https://docsend.com/view/abc
Some text
https://docsend.com/view/abc'''
    links = extract_deck_links(text)
    assert len(links) == 1

def test_extract_no_links():
    links = extract_deck_links('No deck links here, just regular text.')
    assert links == []

def test_extract_random_urls_not_matched():
    text = 'Check out https://example.com/deck.pdf and https://random.io/slides'
    links = extract_deck_links(text)
    assert len(links) == 0


# ---------------------------------------------------------------------------
# format_deck_data_text()
# ---------------------------------------------------------------------------

def test_format_all_fields(sample_deck_data):
    text = format_deck_data_text(sample_deck_data)
    assert 'Acme AI' in text
    assert 'AI-powered' in text
    assert 'Alice Chen' in text
    assert 'Tel Aviv' in text
    assert 'DocuSign' in text

def test_format_sparse_data(sparse_deck_data):
    text = format_deck_data_text(sparse_deck_data)
    assert 'Stealth Co' in text
    # Null fields should not appear
    assert 'None' not in text

def test_format_empty_dict():
    text = format_deck_data_text({})
    assert text == ''

def test_format_competitors_listed(sample_deck_data):
    text = format_deck_data_text(sample_deck_data)
    assert 'Competitors Mentioned: DocuSign, Kofax, ABBYY' in text

def test_format_founders_listed(sample_deck_data):
    text = format_deck_data_text(sample_deck_data)
    assert 'Founders: Alice Chen, Bob Smith' in text
