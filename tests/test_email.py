"""Tests for the shared email sender (lib/email.py).

The underlying gws_gmail_send is mocked so no real emails are sent.
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

# Mock lib.gws before importing lib.email since it imports gws_gmail_send at module level
_fake_gws = MagicMock()
sys.modules['lib.gws'] = _fake_gws

import lib.email as email_mod  # noqa: E402


class TestSendEmail(unittest.TestCase):

    def setUp(self):
        _fake_gws.gws_gmail_send.reset_mock()

    def test_successful_send(self):
        _fake_gws.gws_gmail_send.return_value = True

        result = email_mod.send_email('user@example.com', 'Hello', 'Body text')
        self.assertTrue(result)
        _fake_gws.gws_gmail_send.assert_called_once_with('user@example.com', 'Hello', 'Body text')

    def test_send_failure(self):
        _fake_gws.gws_gmail_send.return_value = None

        result = email_mod.send_email('user@example.com', 'Fail', 'Body')
        self.assertFalse(result)

    def test_send_returns_false_on_false(self):
        _fake_gws.gws_gmail_send.return_value = False

        result = email_mod.send_email('user@example.com', 'Fail', 'Body')
        self.assertFalse(result)

    def test_account_param_ignored(self):
        """The account parameter is kept for API compat but ignored."""
        _fake_gws.gws_gmail_send.return_value = True

        result = email_mod.send_email('user@example.com', 'Subj', 'Body', account='navot')
        self.assertTrue(result)
        # gws_gmail_send is called without account
        _fake_gws.gws_gmail_send.assert_called_once_with('user@example.com', 'Subj', 'Body')

    def test_email_parameters_passed_correctly(self):
        """Verify that to, subject, body are forwarded to gws_gmail_send."""
        _fake_gws.gws_gmail_send.return_value = True

        email_mod.send_email('test@domain.org', 'Subject Line', 'Full body\nwith newlines')
        args = _fake_gws.gws_gmail_send.call_args[0]
        self.assertEqual(args[0], 'test@domain.org')
        self.assertEqual(args[1], 'Subject Line')
        self.assertEqual(args[2], 'Full body\nwith newlines')

    def test_unicode_subject_and_body(self):
        _fake_gws.gws_gmail_send.return_value = True

        result = email_mod.send_email('u@ex.com', 'Shalom \u05e9\u05dc\u05d5\u05dd', 'Body with emoji \u2764')
        self.assertTrue(result)
        args = _fake_gws.gws_gmail_send.call_args[0]
        self.assertIn('\u05e9\u05dc\u05d5\u05dd', args[1])


if __name__ == '__main__':
    unittest.main()
