#!/bin/bash
# Daily Maintenance — OpenClaw auto-update + server upgrade
# Runs daily at 4am UTC via cron.
#
# Install:
#   crontab -e
#   0 4 * * * /root/scripts/daily-maintenance.sh >> /var/log/daily-maintenance.log 2>&1

set +e

TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
LOG_PREFIX="[$TIMESTAMP] Daily Maintenance:"

log()  { echo "$LOG_PREFIX $1"; }
fail() { echo "$LOG_PREFIX FAIL: $1"; }

# ---- OpenClaw Update ----

log "Checking for OpenClaw updates..."

BEFORE=$(openclaw --version 2>/dev/null)
log "Current version: $BEFORE"

UPDATE_OUTPUT=$(openclaw update 2>&1)
UPDATE_RC=$?

AFTER=$(openclaw --version 2>/dev/null)

if [ "$BEFORE" != "$AFTER" ]; then
    log "UPDATED: $BEFORE → $AFTER"

    # Verify WhatsApp reconnected after update
    sleep 15
    status=$(openclaw channels status 2>&1)
    if echo "$status" | grep -q "disconnected"; then
        log "WhatsApp disconnected after update, restarting gateway..."
        openclaw gateway restart 2>&1 || true
        sleep 15
        status=$(openclaw channels status 2>&1)
        if echo "$status" | grep -q "disconnected"; then
            fail "WhatsApp still disconnected after update + restart"
        else
            log "WhatsApp reconnected after post-update restart"
        fi
    else
        log "WhatsApp still connected after update"
    fi
elif [ $UPDATE_RC -eq 0 ]; then
    log "Already on latest: $BEFORE"
else
    fail "Update command failed (rc=$UPDATE_RC)"
fi

# ---- Server Package Upgrades ----

log "Running server package upgrades..."

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq 2>&1 | tail -1
UPGRADE_OUTPUT=$(apt-get upgrade -y -qq 2>&1)
UPGRADE_RC=$?

if [ $UPGRADE_RC -eq 0 ]; then
    UPGRADED=$(echo "$UPGRADE_OUTPUT" | grep -c "^Inst " 2>/dev/null || echo "0")
    log "Server upgrade complete ($UPGRADED packages)"
else
    fail "Server upgrade failed (rc=$UPGRADE_RC)"
fi

# Auto-remove old packages
apt-get autoremove -y -qq 2>&1 || true

# Reboot if needed
if [ -f /var/run/reboot-required ]; then
    log "Reboot required — rebooting now..."
    shutdown -r +1 "Daily maintenance: auto-reboot after package upgrade"
else
    log "No reboot needed."
fi

log "Daily maintenance complete."
