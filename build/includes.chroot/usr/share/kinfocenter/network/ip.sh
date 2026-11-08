#!/bin/sh
# DevOS: visual Network Interfaces page for Info Center (replaces raw `ip | aha` dump).
# Info Center passes darkness as $1 (1 = dark theme).

set -e
DARKNESS="${1:-1}"

# Prefer live project tree while developing, then installed path.
for CAND in \
  /home/imran/project/dev-os/components/networkusage/interfaces_view.py \
  /usr/local/share/devos/components/networkusage/interfaces_view.py \
  /usr/share/devos/components/networkusage/interfaces_view.py
do
  if [ -f "$CAND" ]; then
    exec /usr/bin/python3 "$CAND" "$DARKNESS"
  fi
done

# Fallback if the visual renderer is missing — keep classic output.
AHA_ARGS=""
if [ "$DARKNESS" -eq "1" ]; then
  AHA_ARGS="--black --style 'color:initial' --style 'background-color:initial'"
fi
ip -color -statistics -human-readable address 2>&1 \
  | sed -E 's@^([2-9]|[0-9]{2,}):@\n\1:@g' \
  | aha $AHA_ARGS
