#!/bin/bash
# Wrapper script to run the scheduler with time constraints
# Only runs: 9am Israel time to 6pm NY time, excluding Shabbat
#
# Required environment variables (set in .env):
#   SCHEDULER_DIR    - Path to the scheduler project directory (default: $HOME/openclaw-scheduler)
#   ENV_FILE         - Path to .env file (default: $HOME/.env)
#   PROFILE_FILE     - Path to .profile file (default: $HOME/.profile)

set -e

# Configurable paths
ENV_FILE="${ENV_FILE:-$HOME/.env}"
PROFILE_FILE="${PROFILE_FILE:-$HOME/.profile}"
SCHEDULER_DIR="${SCHEDULER_DIR:-$HOME/openclaw-scheduler}"

# Get current time in different timezones
ISRAEL_TIME=$(TZ='Asia/Jerusalem' date +%H:%M)
ISRAEL_HOUR=$(TZ='Asia/Jerusalem' date +%H)
ISRAEL_DAY=$(TZ='Asia/Jerusalem' date +%u)  # 1=Monday, 7=Sunday

NY_TIME=$(TZ='America/New_York' date +%H:%M)
NY_HOUR=$(TZ='America/New_York' date +%H)

# Log current time
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Time check..."
echo "  Israel time: $ISRAEL_TIME (day $ISRAEL_DAY)"
echo "  NY time: $NY_TIME"

# Check if it's Shabbat (Friday 6pm to Saturday 8pm Israel time)
if [ "$ISRAEL_DAY" -eq 6 ]; then
  # Saturday - don't run all day
  echo "  ⏸ Skipping: Shabbat (Saturday)"
  exit 0
elif [ "$ISRAEL_DAY" -eq 5 ]; then
  # Friday - don't run after 6pm (18:00)
  if [ "$ISRAEL_HOUR" -ge 18 ]; then
    echo "  ⏸ Skipping: Shabbat begins (Friday evening)"
    exit 0
  fi
fi

# Check if before 9am Israel time
if [ "$ISRAEL_HOUR" -lt 9 ]; then
  echo "  ⏸ Skipping: Before 9am Israel time"
  exit 0
fi

# Check if after 6pm NY time (18:00)
if [ "$NY_HOUR" -ge 18 ]; then
  echo "  ⏸ Skipping: After 6pm NY time"
  exit 0
fi

# All checks passed - run the processor
echo "  ✓ Time check passed - running processor"
echo ""

# Safe .env loading (no shell execution)
while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key=$(echo "$key" | xargs)
    [[ "$key" =~ ^[A-Za-z_][A-Za-z_0-9]*$ ]] && export "$key=$value"
done < "$ENV_FILE" 2>/dev/null || true
. "$PROFILE_FILE" 2>/dev/null || true
cd "$SCHEDULER_DIR"
node dist/index.js
