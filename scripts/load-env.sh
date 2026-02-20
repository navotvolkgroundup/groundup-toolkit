#!/bin/bash
# Load specific environment variables from .env for a given job.
# Usage: load-env.sh <job-name> -- <command...>
#
# Instead of `source .env` (which loads ALL secrets into the shell),
# this wrapper only exports the variables each job actually needs.
# This limits the blast radius if a process logs its environment.

set -euo pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${TOOLKIT_DIR}/.env"

if [ ! -f "$ENV_FILE" ]; then
    # No .env file — assume env vars are already injected (e.g. container environment).
    # Skip silently and run the command with whatever is already in the environment.
    shift  # skip job name
    [[ "${1:-}" == "--" ]] && shift
    exec "$@"
fi

# Read .env into an associative array (without exporting everything)
declare -A ALL_VARS
while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"  # trim leading whitespace
    [[ -z "$line" || "$line" == \#* ]] && continue
    line="${line#export }"
    key="${line%%=*}"
    val="${line#*=}"
    val="${val%\"}"; val="${val#\"}"  # strip quotes
    val="${val%\'}"; val="${val#\'}"
    ALL_VARS["$key"]="$val"
done < "$ENV_FILE"

# Helper: export a var from ALL_VARS if it exists
export_var() {
    local key="$1"
    if [[ -n "${ALL_VARS[$key]+x}" ]]; then
        export "$key"="${ALL_VARS[$key]}"
    fi
}

JOB="$1"
shift

# Skip the "--" separator if present
[[ "${1:-}" == "--" ]] && shift

# Export only the variables each job needs
case "$JOB" in
    meeting-reminders)
        export_var GOG_KEYRING_PASSWORD
        export_var GOG_ACCOUNT
        export_var MATON_API_KEY
        export_var ANTHROPIC_API_KEY
        export_var BRAVE_SEARCH_API_KEY
        ;;
    meeting-bot)
        export_var GOG_KEYRING_PASSWORD
        export_var GOG_ACCOUNT
        export_var ANTHROPIC_API_KEY
        ;;
    email-to-deal)
        export_var GOG_KEYRING_PASSWORD
        export_var GOG_ACCOUNT
        export_var MATON_API_KEY
        export_var ANTHROPIC_API_KEY
        ;;
    founder-scout)
        export_var ANTHROPIC_API_KEY
        export_var GOG_KEYRING_PASSWORD
        export_var GOG_ACCOUNT
        ;;
    watchdog)
        export_var ASSISTANT_WHATSAPP_PHONE
        export_var ALERT_PHONE
        export_var ALERT_EMAIL
        export_var GOG_ACCOUNT
        export_var GOG_KEYRING_PASSWORD
        export_var TWILIO_ACCOUNT_SID
        export_var TWILIO_API_KEY_SID
        export_var TWILIO_API_KEY_SECRET
        export_var TWILIO_FROM_NUMBER
        ;;
    *)
        # Fallback: load all vars (same as before, for unknown jobs)
        for key in "${!ALL_VARS[@]}"; do
            export "$key"="${ALL_VARS[$key]}"
        done
        ;;
esac

# Run the command
exec "$@"
