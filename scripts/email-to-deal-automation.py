#!/usr/bin/env python3
"""Email-to-deal automation — thin wrapper for backward compatibility."""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.openclaw'))

from email_to_deal import main

# Re-export all public names for backward compatibility with tests
# that import via importlib from this file path
from email_to_deal.extractor import (
    extract_company_info,
    _extract_company_from_email_domains,
    _extract_company_with_claude,
    _is_bad_company_name,
)
from email_to_deal.config import _is_own_firm_name

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("/var/log/deal-automation.log"),
        ],
    )
    main()
