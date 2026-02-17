#!/bin/bash
# GroundUp Toolkit Health Check & Auto-Recovery
# Runs every 15 minutes via cron
# Checks: gateway, WhatsApp, agents, disk/memory
#
# Required environment variables (set in .env):
#   ALERT_EMAIL     - Email address for alert notifications
#   GOG_ACCOUNT     - Google account used to send alert emails
#   GOG_KEYRING_PASSWORD - Keyring password for GOG authentication

set +e

# Environment
# Safe .env loading (no shell execution)
while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key=$(echo "$key" | xargs)
    [[ "$key" =~ ^[A-Za-z_][A-Za-z_0-9]*$ ]] && export "$key=$value"
done < "$HOME/.env" 2>/dev/null || true
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
ALERT_EMAIL="${ALERT_EMAIL:-admin@yourcompany.com}"
GOG_ACCOUNT="${GOG_ACCOUNT:-assistant@yourcompany.com}"
FAILURES=0
WARNINGS=0

log() {
    echo "[$TIMESTAMP] $1"
}

warn() {
    echo "[$TIMESTAMP] WARN: $1"
    WARNINGS=$((WARNINGS+1))
}

fail() {
    echo "[$TIMESTAMP] FAIL: $1"
    FAILURES=$((FAILURES+1))
}

send_alert() {
    local subject="$1"
    local body="$2"
    . ~/.profile 2>/dev/null || true
    export GOG_KEYRING_PASSWORD="${GOG_KEYRING_PASSWORD}"
    gog gmail send --to "$ALERT_EMAIL" --subject "$subject" --body "$body" --account "$GOG_ACCOUNT" 2>/dev/null || true
    log "Alert email sent to $ALERT_EMAIL"
}

log "====================================="
log "GroundUp Toolkit Health Check Start"
log "====================================="

# ----------------------------------------
# 1. Gateway process check
# ----------------------------------------
log "[1/6] Gateway process check..."
GW_STATUS=$(systemctl --user is-active openclaw-gateway 2>/dev/null || echo "inactive")
if [ "$GW_STATUS" != "active" ]; then
    fail "Gateway not running (status: $GW_STATUS). Restarting..."
    systemctl --user restart openclaw-gateway 2>/dev/null
    sleep 10
    GW_STATUS2=$(systemctl --user is-active openclaw-gateway 2>/dev/null || echo "inactive")
    if [ "$GW_STATUS2" = "active" ]; then
        log "  Gateway restarted successfully"
    else
        fail "Gateway failed to restart!"
        send_alert "CRITICAL: OpenClaw Gateway Down" "The OpenClaw gateway failed to restart. Manual intervention needed."
    fi
else
    log "  Gateway is running"
fi

# ----------------------------------------
# 2. Gateway RPC probe
# ----------------------------------------
log "[2/6] Gateway RPC probe..."
HEALTH_OUTPUT=$(openclaw health 2>&1)
if echo "$HEALTH_OUTPUT" | grep -qi "linked"; then
    log "  Gateway RPC healthy"
else
    fail "Gateway RPC probe failed. Restarting..."
    openclaw gateway restart 2>/dev/null
    sleep 10
fi

# ----------------------------------------
# 3. WhatsApp connection check
# ----------------------------------------
log "[3/6] WhatsApp connection check..."
WA_OUTPUT=$(openclaw channels status --probe 2>&1)
if echo "$WA_OUTPUT" | grep -qi "linked.*running.*connected"; then
    log "  WhatsApp is linked, running, and connected"
elif echo "$WA_OUTPUT" | grep -qi "linked"; then
    warn "WhatsApp linked but may not be fully connected. Restarting gateway..."
    openclaw gateway restart 2>/dev/null
    sleep 15
    # Re-check
    WA_OUTPUT2=$(openclaw channels status --probe 2>&1)
    if echo "$WA_OUTPUT2" | grep -qi "linked.*running.*connected"; then
        log "  WhatsApp recovered after restart"
    else
        fail "WhatsApp failed to reconnect after restart!"
        send_alert "CRITICAL: WhatsApp Disconnected" "WhatsApp is disconnected and failed to recover after gateway restart. Manual intervention needed. Run: openclaw channels login"
    fi
else
    fail "WhatsApp not linked! Restarting gateway..."
    openclaw gateway restart 2>/dev/null
    sleep 15
    WA_OUTPUT2=$(openclaw channels status --probe 2>&1)
    if echo "$WA_OUTPUT2" | grep -qi "linked.*running.*connected"; then
        log "  WhatsApp recovered after restart"
    else
        fail "WhatsApp failed to reconnect!"
        send_alert "CRITICAL: WhatsApp Disconnected" "WhatsApp is disconnected and failed to recover after gateway restart. Manual intervention needed. Run: openclaw channels login"
    fi
fi

# ----------------------------------------
# 4. Agent heartbeat check
# ----------------------------------------
log "[4/6] Agent heartbeat check..."
HB_OUTPUT=$(openclaw status 2>&1 | grep -i "heartbeat")
if echo "$HB_OUTPUT" | grep -qi "disabled"; then
    DISABLED=$(echo "$HB_OUTPUT" | grep -oi 'disabled ([a-z]*)' | sed 's/disabled //g' | tr '\n' ', ')
    warn "Some agent heartbeats are disabled: $DISABLED"
else
    log "  All agent heartbeats enabled"
fi

# ----------------------------------------
# 5. Disk & memory check
# ----------------------------------------
log "[5/6] Disk & memory check..."
DISK_PCT=$(df / | awk 'NR>1{print $5}' | sed 's/%//')
if [ "$DISK_PCT" -ge 90 ]; then
    warn "Disk usage is at ${DISK_PCT}%"
    send_alert "WARN: Disk usage at ${DISK_PCT}%" "Disk usage is at ${DISK_PCT}%. Consider cleanup."
else
    log "  Disk usage: ${DISK_PCT}%"
fi

MEM_PCT=$(free | awk 'NR==2{printf "%.0f\n", $3/$2*100}')
if [ "$MEM_PCT" -ge 90 ]; then
    warn "Memory usage is at ${MEM_PCT}%"
else
    log "  Memory usage: ${MEM_PCT}%"
fi

# ----------------------------------------
# ----------------------------------------
# 5b. Camofox browser check
# ----------------------------------------
log "[5b/6] Camofox browser check..."
CAMOFOX_HEALTH=$(curl -s http://localhost:9377/health 2>/dev/null)
if echo "$CAMOFOX_HEALTH" | grep -q '"ok":true'; then
    log "  Camofox is running"
else
    warn "Camofox not running. Starting..."
    cd "$HOME/.openclaw/workspace/camofox-browser" && PORT=9377 nohup node server.js >> /var/log/camofox.log 2>&1 &
    sleep 5
    CAMOFOX_HEALTH2=$(curl -s http://localhost:9377/health 2>/dev/null)
    if echo "$CAMOFOX_HEALTH2" | grep -q '"ok":true'; then
        log "  Camofox started successfully"
    else
        fail "Camofox failed to start!"
    fi
fi

# 6. Log size check
# ----------------------------------------
log "[6/6] Log size check..."
for logfile in /tmp/openclaw/*.log /var/log/meeting-reminders.log /var/log/meeting-bot.log /var/log/toolkit-health.log; do
    if [ -f "$logfile" ]; then
        SIZE_MB=$(du -m "$logfile" | cut -f1)
        if [ "$SIZE_MB" -ge 500 ]; then
            warn "Log file $logfile is ${SIZE_MB}MB - consider rotation"
        fi
    fi
done
log "  Log sizes OK"

# ----------------------------------------
# Summary
# ----------------------------------------
if [ "$FAILURES" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    log "Health check PASSED - all systems healthy"
else
    log "Health check COMPLETE: $FAILURES failure(s), $WARNINGS warning(s)"
fi
log ""