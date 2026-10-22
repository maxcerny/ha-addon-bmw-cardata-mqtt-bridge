#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# -----------------------------------------------------------------------------
# Non-interactive BMW CarData OAuth2 device flow (PKCE).
#
# Same requests as upstream scripts/bmw_flow.sh, but instead of waiting for a
# keypress it shows the login link in the add-on log and as a Home Assistant
# notification, then polls until the user has approved it. If the code
# expires, a new one is requested.
#
# Usage: bmw_auth.sh <token_dir> <client_id>
# -----------------------------------------------------------------------------
set -uo pipefail

OUT_DIR="$1"
CLIENT_ID="$2"

DEVICE_ENDPOINT="https://customer.bmwgroup.com/gcdm/oauth/device/code"
TOKEN_ENDPOINT="https://customer.bmwgroup.com/gcdm/oauth/token"
SCOPES="authenticate_user openid cardata:streaming:read"
NOTIFICATION_ID="bmw_cardata_auth"

notify() {
    local payload
    payload="$(jq -n --arg t "$1" --arg m "$2" --arg id "$NOTIFICATION_ID" \
        '{title: $t, message: $m, notification_id: $id}')"
    curl -sS -o /dev/null -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        http://supervisor/core/api/services/persistent_notification/create \
        || bashio::log.warning "Could not create Home Assistant notification"
}

dismiss() {
    curl -sS -o /dev/null -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"notification_id\": \"${NOTIFICATION_ID}\"}" \
        http://supervisor/core/api/services/persistent_notification/dismiss || true
}

mkdir -p "$OUT_DIR"

while true; do
    CODE_VERIFIER="$(openssl rand -base64 96 | tr -d '=+/ \n' | cut -c1-96)"
    CODE_CHALLENGE="$(printf '%s' "$CODE_VERIFIER" \
        | openssl dgst -sha256 -binary \
        | openssl base64 -A \
        | tr '+/' '-_' \
        | tr -d '=')"

    bashio::log.info "Requesting BMW device code..."
    RESP="$(curl -sS \
        -H "Accept: application/json" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data-urlencode client_id="$CLIENT_ID" \
        --data-urlencode scope="$SCOPES" \
        --data-urlencode code_challenge="$CODE_CHALLENGE" \
        --data-urlencode code_challenge_method="S256" \
        "$DEVICE_ENDPOINT")"

    DEVICE_CODE="$(jq -r '.device_code // empty' <<<"$RESP" 2>/dev/null)"
    USER_CODE="$(jq -r '.user_code // empty' <<<"$RESP" 2>/dev/null)"
    VERIFY_URL="$(jq -r '.verification_uri_complete // (.verification_uri + "?user_code=" + .user_code)' <<<"$RESP" 2>/dev/null)"
    INTERVAL="$(jq -r '.interval // 5' <<<"$RESP" 2>/dev/null)"
    EXPIRES_IN="$(jq -r '.expires_in // 300' <<<"$RESP" 2>/dev/null)"

    if [[ -z "$DEVICE_CODE" || -z "$VERIFY_URL" ]]; then
        bashio::log.error "Failed to obtain a device code from BMW. Response: ${RESP}"
        bashio::log.error "Check that client_id is correct and that the CarData stream is enabled in the MyBMW portal."
        notify "BMW CarData: login failed" \
            "Could not get a login code from BMW. Check the add-on log and your **client_id**."
        sleep 60
        continue
    fi

    bashio::log.info "-----------------------------------------------------------"
    bashio::log.info "BMW login required. Open this link and log in / approve:"
    bashio::log.info "  ${VERIFY_URL}"
    bashio::log.info "User code: ${USER_CODE} (valid for ~${EXPIRES_IN}s)"
    bashio::log.info "-----------------------------------------------------------"
    notify "BMW CarData: login required" \
        "Open [this BMW login link](${VERIFY_URL}) and approve access (user code **${USER_CODE}**, valid for about $((EXPIRES_IN / 60)) minutes). The add-on continues automatically once you have approved. A new link is created if this one expires."

    LEFT="$EXPIRES_IN"
    while (( LEFT > 0 )); do
        sleep "$INTERVAL"
        LEFT=$((LEFT - INTERVAL))

        TOK="$(curl -sS \
            -H "Content-Type: application/x-www-form-urlencoded" \
            --data-urlencode grant_type="urn:ietf:params:oauth:grant-type:device_code" \
            --data-urlencode device_code="$DEVICE_CODE" \
            --data-urlencode client_id="$CLIENT_ID" \
            --data-urlencode code_verifier="$CODE_VERIFIER" \
            "$TOKEN_ENDPOINT")"

        ERR="$(jq -r '.error // empty' <<<"$TOK" 2>/dev/null)" || ERR="invalid_response"

        case "$ERR" in
            "")
                umask 077
                jq -r '.access_token'  <<<"$TOK" > "$OUT_DIR/access_token.txt"
                jq -r '.id_token'      <<<"$TOK" > "$OUT_DIR/id_token.txt"
                jq -r '.refresh_token' <<<"$TOK" > "$OUT_DIR/refresh_token.txt"
                bashio::log.info "BMW tokens received and saved."
                dismiss
                exit 0
                ;;
            authorization_pending)
                ;;
            slow_down)
                INTERVAL=$((INTERVAL + 5))
                ;;
            access_denied)
                bashio::log.warning "Access was denied in the browser. Requesting a new code..."
                break
                ;;
            expired_token|expired_device_code|invalid_grant)
                bashio::log.warning "Device code expired. Requesting a new code..."
                break
                ;;
            *)
                bashio::log.warning "Unexpected response from BMW token endpoint: ${TOK}"
                ;;
        esac
    done
done
