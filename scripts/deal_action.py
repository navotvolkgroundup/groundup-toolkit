#!/usr/bin/env python3
"""
Deal Action — thin wrapper for HubSpot deal mutations from the dashboard.

Usage:
    python3 scripts/deal_action.py move-stage <deal_id> <stage_id>
    python3 scripts/deal_action.py approach <person_id>
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.hubspot import update_deal_stage


def main():
    if len(sys.argv) < 2:
        print("Usage: deal_action.py <action> [args...]", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]

    if action == 'move-stage':
        if len(sys.argv) < 4:
            print("Usage: deal_action.py move-stage <deal_id> <stage_id>", file=sys.stderr)
            sys.exit(1)
        deal_id = sys.argv[2]
        stage_id = sys.argv[3]
        success = update_deal_stage(deal_id, stage_id)
        result = {"ok": success, "dealId": deal_id, "stage": stage_id}
        print(json.dumps(result))
        sys.exit(0 if success else 1)

    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
