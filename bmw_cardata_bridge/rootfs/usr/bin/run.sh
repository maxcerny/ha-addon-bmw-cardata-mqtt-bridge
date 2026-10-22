#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# -----------------------------------------------------------------------------
# Add-on entrypoint: build the bridge's .env from the add-on options, make sure
# BMW tokens exist (device flow), then run the bridge and keep it running.
# -----------------------------------------------------------------------------
set -uo pipefail

# The bridge reads everything from $XDG_STATE_HOME/bmw-mqtt-bridge
export XDG_STATE_HOME=/data
STATE_DIR="${XDG_STATE_HOME}/bmw-mqtt-bridge"
ENV_FILE="${STATE_DIR}/.env"
CLIENT_FILE="${STATE_DIR}/.client_id"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

CLIENT_ID="$(bashio::config 'client_id')"
GCID="$(bashio::config 'gcid')"

if [[ -z "$CLIENT_ID" || -z "$GCID" ]]; then
    bashio::exit.nok "Please set client_id and gcid in the add-on configuration (see Documentation tab)."
fi

# ---------- local MQTT broker: explicit options win, else the MQTT service ----------
if bashio::config.has_value 'mqtt_host'; then
    MQTT_HOST="$(bashio::config 'mqtt_host')"
    MQTT_PORT="$(bashio::config 'mqtt_port' 1883)"
    MQTT_USER="$(bashio::config 'mqtt_user' '')"
    MQTT_PASSWORD="$(bashio::config 'mqtt_password' '')"
elif bashio::services.available 'mqtt'; then
    MQTT_HOST="$(bashio::services 'mqtt' 'host')"
    MQTT_PORT="$(bashio::services 'mqtt' 'port')"
    MQTT_USER="$(bashio::services 'mqtt' 'username')"
    MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
    if bashio::var.true "$(bashio::services 'mqtt' 'ssl')"; then
        bashio::log.warning "The MQTT service reports SSL, which the bridge does not support. Set mqtt_host/mqtt_port to a plain listener."
    fi
else
    bashio::exit.nok "No MQTT broker found. Install the Mosquitto broker add-on or set mqtt_host in the configuration."
fi
bashio::log.info "Local MQTT broker: ${MQTT_HOST}:${MQTT_PORT}"

# ---------- write .env (the bridge loads it on startup) ----------
umask 077
{
    echo "CLIENT_ID=${CLIENT_ID}"
    echo "GCID=${GCID}"
    echo "LOCAL_HOST=${MQTT_HOST}"
    echo "LOCAL_PORT=${MQTT_PORT}"
    echo "LOCAL_USER=${MQTT_USER}"
    echo "LOCAL_PASSWORD=${MQTT_PASSWORD}"
    echo "LOCAL_PREFIX=$(bashio::config 'topic_prefix' 'bmw/')"
    echo "SPLIT_TOPICS=$(bashio::config.true 'split_topics' && echo 1 || echo 0)"
    echo "MQTT_RETAIN=$(bashio::config.true 'mqtt_retain' && echo 1 || echo 0)"
    echo "STATUS_STABLE_DELAY=$(bashio::config 'status_stable_delay' 5)"
    bashio::config.has_value 'bmw_host' && echo "BMW_HOST=$(bashio::config 'bmw_host')"
    bashio::config.has_value 'bmw_port' && echo "BMW_PORT=$(bashio::config 'bmw_port')"
} > "$ENV_FILE"

clear_tokens() {
    rm -f "${STATE_DIR}/id_token.txt" "${STATE_DIR}/refresh_token.txt" \
          "${STATE_DIR}/access_token.txt" "${STATE_DIR}/token_refresh_response.json"
}

# ---------- forced re-authentication ----------
if bashio::config.true 'reauthenticate'; then
    bashio::log.info "reauthenticate is enabled: discarding stored BMW tokens."
    clear_tokens
    # Switch the option back off so the next restart does not log in again
    NEW_OPTIONS="$(jq '.reauthenticate = false | {options: .}' /data/options.json)"
    curl -sS -o /dev/null -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$NEW_OPTIONS" \
        http://supervisor/addons/self/options \
        || bashio::log.warning "Could not reset the reauthenticate option; please turn it off manually."
fi

# Tokens belong to a client_id; a new client_id needs a new login
if [[ -f "$CLIENT_FILE" && "$(cat "$CLIENT_FILE")" != "$CLIENT_ID" ]]; then
    bashio::log.info "client_id changed: discarding stored BMW tokens."
    clear_tokens
fi
echo "$CLIENT_ID" > "$CLIENT_FILE"

# ---------- optional Home Assistant MQTT discovery ----------
if bashio::config.true 'ha_discovery'; then
    if ! bashio::config.true 'split_topics'; then
        bashio::log.warning "ha_discovery needs split_topics enabled; no entities will be created."
    fi
    PREFIX="$(bashio::config 'topic_prefix' 'bmw/')"
    [[ "$PREFIX" == */ ]] || PREFIX="${PREFIX}/"
    (
        export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD
        export TOPIC_PREFIX="$PREFIX" DISCOVERY_PREFIX="$(bashio::config 'discovery_prefix' 'homeassistant')"
        while true; do
            python3 /usr/bin/bmw_discovery.py
            bashio::log.warning "Discovery service exited, restarting in 10 seconds..."
            sleep 10
        done
    ) &
fi

# ---------- main loop ----------
while true; do
    if [[ ! -s "${STATE_DIR}/id_token.txt" || ! -s "${STATE_DIR}/refresh_token.txt" ]]; then
        /usr/bin/bmw_auth.sh "$STATE_DIR" "$CLIENT_ID"
    fi

    bashio::log.info "Starting BMW CarData MQTT bridge..."
    /usr/bin/bmw_mqtt_bridge
    RC=$?
    bashio::log.warning "Bridge exited with code ${RC}."

    # A rejected refresh token means the login is no longer valid: log in again
    if [[ -f "${STATE_DIR}/token_refresh_response.json" ]] \
        && [[ "$(jq -r '.error // empty' "${STATE_DIR}/token_refresh_response.json" 2>/dev/null)" == "invalid_grant" ]]; then
        bashio::log.warning "BMW rejected the refresh token, a new login is required."
        clear_tokens
    fi

    bashio::log.info "Restarting in 30 seconds..."
    sleep 30
done
