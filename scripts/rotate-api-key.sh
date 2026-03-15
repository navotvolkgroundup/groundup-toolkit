#!/bin/bash
# Rotate API Key — safely update a secret in .env and restart affected services.
#
# Usage:
#   scripts/rotate-api-key.sh <KEY_NAME> <NEW_VALUE>
#
# Example:
#   scripts/rotate-api-key.sh ANTHROPIC_API_KEY sk-ant-new-key-here
#
# What it does:
#   1. Validates inputs
#   2. Backs up current .env
#   3. Replaces the key value in .env
#   4. Restarts the OpenClaw gateway (picks up new env)
#   5. Logs the rotation event

set -euo pipefail

ENV_FILE="${HOME}/.env"
TOOLKIT_ROOT="${TOOLKIT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ROTATION_LOG="${TOOLKIT_ROOT}/data/key-rotations.log"
TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

log() { echo "[$TIMESTAMP] $1"; }

if [ $# -lt 2 ]; then
    echo "Usage: $0 <KEY_NAME> <NEW_VALUE>"
    echo ""
    echo "Common keys:"
    echo "  ANTHROPIC_API_KEY    - Claude API key"
    echo "  MATON_API_KEY        - Maton gateway API key"
    echo "  BRAVE_API_KEY        - Brave Search API key"
    echo "  TWILIO_API_KEY_SID   - Twilio API key"
    exit 1
fi

KEY_NAME="$1"
NEW_VALUE="$2"

# Validate key name (alphanumeric + underscore only)
if ! echo "$KEY_NAME" | grep -qE '^[A-Za-z_][A-Za-z_0-9]*$'; then
    echo "Error: Invalid key name '$KEY_NAME'" >&2
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: $ENV_FILE not found" >&2
    exit 1
fi

# Check key exists in .env
if ! grep -q "^${KEY_NAME}=" "$ENV_FILE"; then
    echo "Error: Key '$KEY_NAME' not found in $ENV_FILE" >&2
    echo "Available keys:"
    grep -oE '^[A-Za-z_][A-Za-z_0-9]*=' "$ENV_FILE" | sed 's/=$/  /' | sort
    exit 1
fi

# Backup current .env
BACKUP="${ENV_FILE}.bak.${TIMESTAMP//[:T]/-}"
cp "$ENV_FILE" "$BACKUP"
log "Backed up $ENV_FILE → $BACKUP"

# Get old value (masked) for logging
OLD_VALUE=$(grep "^${KEY_NAME}=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed 's/^["'"'"']//;s/["'"'"']$//')
OLD_MASKED="${OLD_VALUE:0:6}...${OLD_VALUE: -4}"
NEW_MASKED="${NEW_VALUE:0:6}...${NEW_VALUE: -4}"

# Replace the key value
# Use a temp file to avoid sed -i portability issues
TMPFILE=$(mktemp "${ENV_FILE}.XXXXXX")
while IFS= read -r line || [ -n "$line" ]; do
    if echo "$line" | grep -q "^${KEY_NAME}="; then
        echo "${KEY_NAME}=${NEW_VALUE}"
    else
        echo "$line"
    fi
done < "$ENV_FILE" > "$TMPFILE"

# Atomic replace
mv "$TMPFILE" "$ENV_FILE"
chmod 600 "$ENV_FILE"

log "Updated $KEY_NAME: $OLD_MASKED → $NEW_MASKED"

# Log rotation event
mkdir -p "$(dirname "$ROTATION_LOG")"
echo "$TIMESTAMP rotated $KEY_NAME ($OLD_MASKED → $NEW_MASKED)" >> "$ROTATION_LOG"

# Restart gateway to pick up new env
log "Restarting OpenClaw gateway..."
if systemctl --user restart openclaw-gateway 2>/dev/null; then
    sleep 5
    STATUS=$(systemctl --user is-active openclaw-gateway 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "active" ]; then
        log "Gateway restarted successfully"
    else
        log "WARNING: Gateway status is '$STATUS' after restart"
    fi
else
    log "Note: systemctl restart skipped (not available or not running as user service)"
fi

log "Key rotation complete for $KEY_NAME"
