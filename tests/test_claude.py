"""Tests for the shared Claude API client (lib/claude.py).

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
_fake_config.anthropic_api_key = 'test-anthropic-key'

_fake_lib_config = MagicMock()
_fake_lib_config.config = _fake_config

if 'lib' in sys.modules and not hasattr(sys.modules['lib'], '__path__'):
    del sys.modules['lib']
sys.modules['lib.config'] = _fake_lib_config

import lib.claude as claude  # noqa: E402


class TestCallClaude(unittest.TestCase):

    @patch('lib.claude.requests.post')
    def test_successful_call(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'content': [{'text': 'Hello from Claude'}]
        }
        mock_post.return_value = mock_resp

        result = claude.call_claude('Say hello')
        self.assertEqual(result, 'Hello from Claude')

        # Verify correct headers and payload
        call_kwargs = mock_post.call_args
        self.assertEqual(call_kwargs[1]['headers']['x-api-key'], 'test-anthropic-key')
        payload = call_kwargs[1]['json']
        self.assertEqual(payload['messages'][0]['content'], 'Say hello')

    @patch('lib.claude.time.sleep')
    @patch('lib.claude.requests.post')
    def test_retry_on_rate_limit_429(self, mock_post, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {'content': [{'text': 'success'}]}

        mock_post.side_effect = [rate_resp, ok_resp]

        result = claude.call_claude('test', max_retries=3)
        self.assertEqual(result, 'success')
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(15)  # min(15 * 1, 60)

    @patch('lib.claude.time.sleep')
    @patch('lib.claude.requests.post')
    def test_retry_on_overloaded_529(self, mock_post, mock_sleep):
        overloaded_resp = MagicMock()
        overloaded_resp.status_code = 529

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {'content': [{'text': 'recovered'}]}

        mock_post.side_effect = [overloaded_resp, ok_resp]

        result = claude.call_claude('test', max_retries=3)
        self.assertEqual(result, 'recovered')
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(30)

    @patch('lib.claude.time.sleep')
    @patch('lib.claude.requests.post')
    def test_max_retries_exhausted(self, mock_post, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        mock_post.return_value = rate_resp

        result = claude.call_claude('test', max_retries=2)
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 2)

    @patch('lib.claude.requests.post')
    def test_different_model_parameter(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'content': [{'text': 'haiku response'}]}
        mock_post.return_value = mock_resp

        result = claude.call_claude('test', model='claude-haiku-4-5')
        self.assertEqual(result, 'haiku response')

        payload = mock_post.call_args[1]['json']
        self.assertEqual(payload['model'], 'claude-haiku-4-5')

    @patch('lib.claude.requests.post')
    def test_system_prompt_included(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'content': [{'text': 'ok'}]}
        mock_post.return_value = mock_resp

        claude.call_claude('test', system_prompt='Be helpful')
        payload = mock_post.call_args[1]['json']
        self.assertEqual(payload['system'], 'Be helpful')

    @patch('lib.claude.requests.post')
    def test_system_prompt_omitted_when_empty(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'content': [{'text': 'ok'}]}
        mock_post.return_value = mock_resp

        claude.call_claude('test')
        payload = mock_post.call_args[1]['json']
        self.assertNotIn('system', payload)

    @patch('lib.claude.requests.post')
    def test_non_retryable_error_returns_none(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_post.return_value = mock_resp

        result = claude.call_claude('test')
        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 1)

    @patch('lib.claude.requests.post')
    def test_request_exception_returns_none(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError('network down')

        result = claude.call_claude('test')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
