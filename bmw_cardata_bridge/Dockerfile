ARG BUILD_FROM
# -----------------------------------------------------------------------------
# Build stage: compile the upstream bridge from a pinned commit
FROM $BUILD_FROM AS builder

ARG BRIDGE_REPO
ARG BRIDGE_COMMIT

RUN apk add --no-cache build-base git mosquitto-dev curl-dev pkgconf

WORKDIR /build
RUN git init -q . \
    && git remote add origin "${BRIDGE_REPO}" \
    && git fetch -q --depth 1 origin "${BRIDGE_COMMIT}" \
    && git checkout -q FETCH_HEAD \
    && g++ -std=c++17 -O2 -pthread src/bmw_mqtt_bridge.cpp -o bmw_mqtt_bridge \
       $(pkg-config --cflags --libs libmosquitto) -lcurl

# -----------------------------------------------------------------------------
# Runtime stage
FROM $BUILD_FROM

RUN apk add --no-cache mosquitto-libs libcurl libstdc++ ca-certificates curl jq openssl

COPY --from=builder /build/bmw_mqtt_bridge /usr/bin/bmw_mqtt_bridge
COPY rootfs /

RUN chmod a+x /usr/bin/run.sh /usr/bin/bmw_auth.sh

CMD [ "/usr/bin/run.sh" ]
