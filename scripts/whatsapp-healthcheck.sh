#!/bin/bash
# WhatsApp Health Check — monitors connection and auto-recovers
# Runs every hour via cron. On failure: restarts gateway, retries,
# then logs the outcome.
#
# Install:
#   crontab -e
#   0 * * * * /root/scripts/whatsapp-healthcheck.sh >> /var/log/whatsapp-healthcheck.log 2>&1

set +e

TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
LOG_PREFIX="[$TIMESTAMP] WhatsApp Health:"

log()  { echo "$LOG_PREFIX $1"; }
fail() { echo "$LOG_PREFIX FAIL: $1"; }

# Check if WhatsApp is connected by parsing openclaw channels status
check_whatsapp() {
    status=$(openclaw channels status 2>&1)
    if echo "$status" | grep -q "connected"; then
        # Make sure it's not "disconnected"
        if echo "$status" | grep -q "disconnected"; then
            return 1
        fi
        return 0
    fi
    return 1
}

# Restart the gateway
restart_gateway() {
    log "Restarting gateway..."
    openclaw gateway restart 2>&1 || true
    # Give it time to reconnect
    sleep 15
    log "Gateway restarted, checking status..."
}

# ---- Main ----

log "Starting health check..."

# Step 1: Check if WhatsApp is connected
if check_whatsapp; then
    log "OK — WhatsApp is connected"
    exit 0
fi

# Step 2: Not connected — restart gateway
fail "WhatsApp is disconnected, attempting auto-recovery..."
restart_gateway

if check_whatsapp; then
    log "RECOVERED — WhatsApp reconnected after gateway restart"
    exit 0
fi

# Step 3: Second restart attempt
fail "Still disconnected after first restart, trying again..."
restart_gateway

if check_whatsapp; then
    log "RECOVERED — WhatsApp reconnected after second restart"
    exit 0
fi

# Step 4: Give up
fail "WhatsApp is DOWN — could not auto-recover. May need QR re-scan (openclaw channels login)."
exit 1
