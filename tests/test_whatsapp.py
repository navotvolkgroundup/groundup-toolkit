"""Tests for the shared WhatsApp sender (lib/whatsapp.py).

All subprocess calls are mocked via unittest.mock.patch so no real
commands are executed.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the repo root is on sys.path and mock lib.config before importing
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

_fake_config = MagicMock()
_fake_lib_config = MagicMock()
_fake_lib_config.config = _fake_config

if 'lib' in sys.modules and not hasattr(sys.modules['lib'], '__path__'):
    del sys.modules['lib']
sys.modules['lib.config'] = _fake_lib_config

import lib.whatsapp as whatsapp  # noqa: E402


class TestSendWhatsApp(unittest.TestCase):

    @patch('lib.whatsapp.subprocess.run')
    def test_successful_send(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        result = whatsapp.send_whatsapp('+1234567890', 'Hello!')
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 1)

        cmd = mock_run.call_args[0][0]
        self.assertIn('openclaw', cmd[0])
        self.assertIn('--target', cmd)
        self.assertIn('+1234567890', cmd)
        self.assertIn('--message', cmd)
        self.assertIn('Hello!', cmd)

    @patch('lib.whatsapp.time.sleep')
    @patch('lib.whatsapp.subprocess.run')
    def test_retry_on_failure(self, mock_run, mock_sleep):
        fail_result = MagicMock(returncode=1, stderr='connection lost')
        ok_result = MagicMock(returncode=0)
        mock_run.side_effect = [fail_result, ok_result]

        result = whatsapp.send_whatsapp('+1234567890', 'Retry test', max_retries=3)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(3)

    @patch('lib.whatsapp.time.sleep')
    @patch('lib.whatsapp.subprocess.run')
    def test_all_retries_exhausted(self, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(returncode=1, stderr='error')

        result = whatsapp.send_whatsapp('+1234567890', 'Fail', max_retries=2)
        self.assertFalse(result)
        self.assertEqual(mock_run.call_count, 2)

    @patch('lib.whatsapp.subprocess.run')
    def test_message_formatting_with_account(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        whatsapp.send_whatsapp('+9876543210', 'Test msg', account='main')

        cmd = mock_run.call_args[0][0]
        self.assertIn('--account', cmd)
        self.assertIn('main', cmd)

    @patch('lib.whatsapp.subprocess.run')
    def test_no_account_flag_when_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        whatsapp.send_whatsapp('+1234567890', 'Test')

        cmd = mock_run.call_args[0][0]
        self.assertNotIn('--account', cmd)

    @patch('lib.whatsapp.time.sleep')
    @patch('lib.whatsapp.subprocess.run')
    def test_exception_triggers_retry(self, mock_run, mock_sleep):
        ok_result = MagicMock(returncode=0)
        mock_run.side_effect = [Exception('timeout'), ok_result]

        result = whatsapp.send_whatsapp('+1234567890', 'Test', max_retries=2)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()


if __name__ == '__main__':
    unittest.main()
