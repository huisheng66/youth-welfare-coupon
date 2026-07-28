#!/usr/bin/env bash
set -uo pipefail
echo "==> probe targets"
HIP=$(awk '/nameserver/{print $2; exit}' /etc/resolv.conf)
echo "resolv_host=$HIP"
# Windows host IP via default route (WSL2)
WINIP=$(ip route show default 2>/dev/null | awk '{print $3; exit}')
echo "default_gw=$WINIP"

for t in \
  "http://127.0.0.1:19001" \
  "http://localhost:19001" \
  "http://${HIP}:19001" \
  "http://${WINIP}:19001" \
  "http://host.docker.internal:19001"
do
  code=$(curl -s -o /tmp/h.json -w "%{http_code}" --connect-timeout 2 "$t/api/health" || echo fail)
  echo "$code  $t"
  if [[ "$code" == "200" ]]; then
    echo "OK_TARGET=$t"
    cat /tmp/h.json
    echo
    exit 0
  fi
done
echo "NO_TARGET"
exit 1
