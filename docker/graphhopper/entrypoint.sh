#!/usr/bin/env sh
set -eu

: "${GRAPHHOPPER_CONFIG:=/config/config.yml}"
: "${GRAPHHOPPER_JAVA_OPTS:=-Xms1g -Xmx2g}"

rm -f /tmp/graphhopper-ready

java ${GRAPHHOPPER_JAVA_OPTS} \
  -cp "/graphhopper/graphhopper-web.jar:/graphhopper/plugins/*" \
  kr.ssafy.ieumgil.graphhopper.IeumGraphHopperApplication \
  server "${GRAPHHOPPER_CONFIG}" &

pid="$!"

trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' INT TERM

until curl -fsS "http://127.0.0.1:8989/health" >/dev/null 2>&1; do
  if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid"
  fi
  sleep 1
done

touch /tmp/graphhopper-ready
wait "$pid"
