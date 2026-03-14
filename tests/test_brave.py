"""Tests for the shared Brave Search API client (lib/brave.py).

All HTTP calls are mocked via unittest.mock.patch so no real API requests
are made.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the repo root is on sys.path and mock lib.config before importing
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

_fake_config = MagicMock()
_fake_config.brave_search_api_key = 'test-brave-key'

_fake_lib_config = MagicMock()
_fake_lib_config.config = _fake_config

if 'lib' in sys.modules and not hasattr(sys.modules['lib'], '__path__'):
    del sys.modules['lib']
sys.modules['lib.config'] = _fake_lib_config

import lib.brave as brave  # noqa: E402


class TestBraveSearch(unittest.TestCase):

    @patch('lib.brave.requests.get')
    def test_successful_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'web': {
                'results': [
                    {'title': 'Result 1', 'url': 'https://example.com/1', 'description': 'Desc 1'},
                    {'title': 'Result 2', 'url': 'https://example.com/2', 'description': 'Desc 2'},
                ]
            }
        }
        mock_get.return_value = mock_resp

        results = brave.brave_search('test query')
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['title'], 'Result 1')
        self.assertEqual(results[1]['url'], 'https://example.com/2')

        # Verify API was called with correct params
        call_kwargs = mock_get.call_args
        self.assertIn('X-Subscription-Token', call_kwargs[1]['headers'])
        self.assertEqual(call_kwargs[1]['params']['q'], 'test query')

    @patch('lib.brave.time.sleep')
    @patch('lib.brave.requests.get')
    def test_retry_on_5xx(self, mock_get, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.status_code = 503

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {'web': {'results': [{'title': 'OK', 'url': 'u', 'description': 'd'}]}}

        mock_get.side_effect = [fail_resp, ok_resp]

        results = brave.brave_search('test')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'OK')
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('lib.brave.time.sleep')
    @patch('lib.brave.requests.get')
    def test_retry_on_connection_error(self, mock_get, mock_sleep):
        import requests as real_requests

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {'web': {'results': [{'title': 'OK', 'url': 'u', 'description': 'd'}]}}

        mock_get.side_effect = [real_requests.exceptions.ConnectionError('refused'), ok_resp]

        results = brave.brave_search('test')
        self.assertEqual(len(results), 1)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('lib.brave.requests.get')
    def test_empty_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'web': {'results': []}}
        mock_get.return_value = mock_resp

        results = brave.brave_search('nothing here')
        self.assertEqual(results, [])

    def test_no_api_key_returns_empty(self):
        original = brave.BRAVE_SEARCH_API_KEY
        try:
            brave.BRAVE_SEARCH_API_KEY = ''
            results = brave.brave_search('test')
            self.assertEqual(results, [])
        finally:
            brave.BRAVE_SEARCH_API_KEY = original

    @patch('lib.brave.time.sleep')
    @patch('lib.brave.requests.get')
    def test_all_retries_exhausted(self, mock_get, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        mock_get.return_value = fail_resp

        results = brave.brave_search('test')
        self.assertEqual(results, [])
        self.assertEqual(mock_get.call_count, brave._MAX_RETRIES)

    @patch('lib.brave.requests.get')
    def test_non_retryable_error_returns_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        results = brave.brave_search('test')
        self.assertEqual(results, [])
        self.assertEqual(mock_get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
