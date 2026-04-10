"""Tests for the shared WhatsApp sender (lib/whatsapp.py).

All subprocess calls are mocked via unittest.mock.patch so no real
commands are executed.
"""

import os
import sys
import subprocess
import time
import unittest
from unittest.mock import patch, MagicMock

# Ensure the repo root is on sys.path and mock lib.config before importing
REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, REPO_ROOT)

_fake_config = MagicMock()
_fake_lib_config = MagicMock()
_fake_lib_config.config = _fake_config

sys.modules.setdefault('lib.config', _fake_lib_config)

import lib.whatsapp as whatsapp  # noqa: E402


class TestSendWhatsApp(unittest.TestCase):

    def setUp(self):
        whatsapp.reset_circuit_breaker()

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_successful_send(self, mock_run, _mock_which):
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

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(time, 'sleep')
    @patch.object(subprocess, 'run')
    def test_retry_on_failure(self, mock_run, mock_sleep, _mock_which):
        fail_result = MagicMock(returncode=1, stderr='connection lost')
        ok_result = MagicMock(returncode=0)
        mock_run.side_effect = [fail_result, ok_result]

        result = whatsapp.send_whatsapp('+1234567890', 'Retry test', max_retries=3)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(5)

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(time, 'sleep')
    @patch.object(subprocess, 'run')
    def test_all_retries_exhausted(self, mock_run, mock_sleep, _mock_which):
        mock_run.return_value = MagicMock(returncode=1, stderr='error')

        result = whatsapp.send_whatsapp('+1234567890', 'Fail', max_retries=2)
        self.assertFalse(result)
        self.assertEqual(mock_run.call_count, 2)

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_message_formatting_with_custom_account(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0)

        whatsapp.send_whatsapp('+9876543210', 'Test msg', account='secondary')

        cmd = mock_run.call_args[0][0]
        self.assertIn('--account', cmd)
        self.assertIn('secondary', cmd)

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_default_and_main_accounts_skipped(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0)

        for name in ('default', 'main'):
            whatsapp.send_whatsapp('+9876543210', 'Test', account=name)
            cmd = mock_run.call_args[0][0]
            self.assertNotIn('--account', cmd, f"account='{name}' should be skipped")

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_no_account_flag_when_none(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0)

        whatsapp.send_whatsapp('+1234567890', 'Test')

        cmd = mock_run.call_args[0][0]
        self.assertNotIn('--account', cmd)

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(time, 'sleep')
    @patch.object(subprocess, 'run')
    def test_exception_triggers_retry(self, mock_run, mock_sleep, _mock_which):
        ok_result = MagicMock(returncode=0)
        mock_run.side_effect = [Exception('some error'), ok_result]

        result = whatsapp.send_whatsapp('+1234567890', 'Test', max_retries=2)
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_timeout_does_not_retry(self, mock_run, _mock_which):
        """TimeoutExpired should fail immediately without retrying."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['openclaw'], timeout=30)

        result = whatsapp.send_whatsapp('+1234567890', 'Test', max_retries=3)
        self.assertFalse(result)
        self.assertEqual(mock_run.call_count, 1)  # no retries

    @patch('shutil.which', return_value=None)
    @patch.object(subprocess, 'run')
    def test_openclaw_not_found(self, mock_run, _mock_which):
        """Should fail immediately if openclaw is not in PATH."""
        result = whatsapp.send_whatsapp('+1234567890', 'Test')
        self.assertFalse(result)
        mock_run.assert_not_called()

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_circuit_breaker_trips_after_timeouts(self, mock_run, _mock_which):
        """After consecutive failures, circuit breaker should skip further sends."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['openclaw'], timeout=30)

        # First two calls trip the circuit breaker
        whatsapp.send_whatsapp('+1234567890', 'Test1')
        whatsapp.send_whatsapp('+1234567890', 'Test2')
        self.assertEqual(mock_run.call_count, 2)

        # Third call should be skipped entirely
        result = whatsapp.send_whatsapp('+1234567890', 'Test3')
        self.assertFalse(result)
        self.assertEqual(mock_run.call_count, 2)  # no new call

    @patch('shutil.which', return_value='/usr/local/bin/openclaw')
    @patch.object(subprocess, 'run')
    def test_circuit_breaker_resets(self, mock_run, _mock_which):
        """reset_circuit_breaker() should allow sends again."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['openclaw'], timeout=30)
        whatsapp.send_whatsapp('+1234567890', 'Test1')
        whatsapp.send_whatsapp('+1234567890', 'Test2')

        whatsapp.reset_circuit_breaker()
        self.assertTrue(whatsapp.whatsapp_available())

    def test_empty_phone_skipped(self):
        result = whatsapp.send_whatsapp('', 'Test')
        self.assertFalse(result)

        result = whatsapp.send_whatsapp('  ', 'Test')
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
