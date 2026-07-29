#!/usr/bin/env bash
set -u
HOST="${1:-198.44.182.107}"
PORT="${2:-22}"
KEYS=(id_ed25519 id_ed25519_fuwuqi id_ed25519_gmail)
USERS=(root ubuntu admin huisheng debian ec2-user)

for key in "${KEYS[@]}"; do
  keypath="$HOME/.ssh/$key"
  if [[ ! -f "$keypath" ]]; then
    echo "skip missing $keypath"
    continue
  fi
  for user in "${USERS[@]}"; do
    echo "try $user@$HOST -i $key ..."
    if out=$(ssh -i "$keypath" \
      -o BatchMode=yes \
      -o ConnectTimeout=8 \
      -o StrictHostKeyChecking=accept-new \
      -o IdentitiesOnly=yes \
      -p "$PORT" \
      "${user}@${HOST}" \
      "echo OK; whoami; hostname; uname -a" 2>&1); then
      echo "SUCCESS user=$user key=$key"
      echo "$out"
      exit 0
    else
      echo "fail: $out" | head -c 200
      echo
    fi
  done
done
echo "ALL_FAILED"
exit 1
