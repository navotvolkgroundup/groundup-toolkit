#!/bin/bash
# WhatsApp Watchdog - Detects dead connections via actual send test
# Runs every 5 minutes via cron
# On failure: restarts gateway, retries, then sends alert via Twilio
#
# Required environment variables (set in .env):
#   ASSISTANT_WHATSAPP_PHONE - Phone number of the assistant (WhatsApp target)
#   ALERT_PHONE              - Phone number to call/alert on failure
#   ALERT_EMAIL              - Email address for alert notifications
#   GOG_ACCOUNT              - Google account used to send alert emails
#   GOG_KEYRING_PASSWORD     - Keyring password for GOG authentication
#   TWILIO_ACCOUNT_SID       - Twilio account SID (optional, for call alerts)
#   TWILIO_API_KEY_SID       - Twilio API key SID (optional)
#   TWILIO_API_KEY_SECRET    - Twilio API key secret (optional)
#   TWILIO_FROM_NUMBER       - Twilio caller ID number (optional)

set +e
source "$HOME/.env" 2>/dev/null || true

TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
ASSISTANT_PHONE="${ASSISTANT_WHATSAPP_PHONE:-+1234567890}"
ALERT_PHONE="${ALERT_PHONE:-+1234567890}"
ALERT_EMAIL="${ALERT_EMAIL:-admin@yourcompany.com}"
GOG_ACCOUNT="${GOG_ACCOUNT:-assistant@yourcompany.com}"
STATE_FILE="/tmp/whatsapp-watchdog-state"
LOG_PREFIX="[$TIMESTAMP] WhatsApp Watchdog:"

log()  { echo "$LOG_PREFIX $1"; }
fail() { echo "$LOG_PREFIX FAIL: $1"; }

# Cooldown: don't alert more than once per hour
last_alert=$(cat "$STATE_FILE" 2>/dev/null || echo "0")
now=$(date +%s)
cooldown=3600  # 1 hour

# Try sending a test message. Returns 0 on success, 1 on failure.
try_send() {
    result=$(openclaw message send --channel whatsapp \
        --target "$ASSISTANT_PHONE" \
        --message "." 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        return 0
    else
        fail "Send failed: $result"
        return 1
    fi
}

# Restart the gateway process
restart_gateway() {
    log "Restarting gateway..."
    pkill -f openclaw-gateway 2>/dev/null
    sleep 3
    nohup openclaw gateway > /tmp/gateway.log 2>&1 &
    sleep 8  # give it time to initialize
    log "Gateway restarted (PID: $(pgrep -f openclaw-gateway))"
}

# Send alert via Twilio call and email
send_alert() {
    if [ -z "$TWILIO_ACCOUNT_SID" ] || [ -z "$TWILIO_API_KEY_SID" ] || [ -z "$TWILIO_API_KEY_SECRET" ] || [ -z "$TWILIO_FROM_NUMBER" ]; then
        log "Twilio not configured, skipping call alert"
    else
        # Check cooldown
        elapsed=$(( now - last_alert ))
        if [ "$elapsed" -lt "$cooldown" ]; then
            log "Alert cooldown active (${elapsed}s < ${cooldown}s), skipping"
            return
        fi

        log "Calling $ALERT_PHONE to alert about WhatsApp failure..."
        twiml='<Response><Say voice="alice">Hey, the assistant WhatsApp is down and could not auto-recover. Please SSH into the server and run: openclaw channels login, to scan the QR code.</Say><Pause length="2"/><Say voice="alice">Again, WhatsApp is down. SSH to the server and run openclaw channels login.</Say></Response>'

        # Write Twilio credentials to a temp netrc file so they don't appear
        # in shell command strings, ps output, or log files.
        _twilio_netrc=$(mktemp /tmp/.twilio-netrc.XXXXXX)
        chmod 600 "$_twilio_netrc"
        printf 'machine api.twilio.com\n  login %s\n  password %s\n' \
            "$TWILIO_API_KEY_SID" "$TWILIO_API_KEY_SECRET" > "$_twilio_netrc"

        curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Calls.json" \
            --netrc-file "$_twilio_netrc" \
            -d "To=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$ALERT_PHONE'))")" \
            -d "From=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$TWILIO_FROM_NUMBER'))")" \
            --data-urlencode "Twiml=$twiml" > /dev/null 2>&1

        rm -f "$_twilio_netrc"
    fi

    # Also send email alert (GOG_KEYRING_PASSWORD is already in env from .env source)
    gog gmail send --to "$ALERT_EMAIL" \
        --subject "Assistant WhatsApp is DOWN - QR scan needed" \
        --body "WhatsApp failed the send test and could not auto-recover after gateway restart. SSH to the server and run: openclaw channels login" \
        --account "$GOG_ACCOUNT" --force --no-input 2>/dev/null || true

    echo "$now" > "$STATE_FILE"
    log "Alert sent (call + email)"
}

# ---- Main ----

log "Starting health check..."

# Step 1: Try sending
if try_send; then
    log "OK - WhatsApp is healthy"
    # Clear any previous failure state
    echo "0" > "$STATE_FILE" 2>/dev/null
    exit 0
fi

# Step 2: Send failed — restart gateway and retry
log "Send test failed, attempting auto-recovery..."
restart_gateway

if try_send; then
    log "RECOVERED - WhatsApp working after gateway restart"
    echo "0" > "$STATE_FILE" 2>/dev/null
    exit 0
fi

# Step 3: Still failing — send alert
fail "WhatsApp is DOWN and cannot auto-recover. Needs QR re-scan."
send_alert
exit 1
