#!/bin/sh
# Roundtable Souls update watchdog (Linux AppImage). The launcher copies this script to its data folder and starts
# it in its own session just before Velopack applies an update; it outlives the launcher.
#
#   1. wait until Velopack has replaced the AppImage (its inode changes), at most WAIT_APPLY seconds;
#   2. give the new version WAIT_READY seconds to write STATE/ready-VERSION;
#   3. otherwise: stop it, delete its packages from Velopack's cache, write STATE/rollback.json, put the kept
#      AppImage of the previous version back and start it; it reports the rollback and stops offering VERSION.
#
# usage: update-watchdog.sh APPIMAGE VERSION KEPT_APPIMAGE STATE WAIT_APPLY WAIT_READY PACK_ID
APP=$1
VERSION=$2
KEPT=$3
STATE=$4
WAIT_APPLY=${5:-600}
WAIT_READY=${6:-90}
PACK=$7
LOG="$STATE/watchdog.log"

say() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

before=$(stat -c %i "$APP" 2>/dev/null)
say "waiting for Velopack to apply $VERSION to $APP"
i=0
while [ "$(stat -c %i "$APP" 2>/dev/null)" = "$before" ]; do
    i=$((i + 1))
    if [ "$i" -gt $((WAIT_APPLY * 2)) ]; then
        say "$VERSION was not applied within $WAIT_APPLY s; nothing to undo"
        exit 0
    fi
    sleep 0.5
done

say "$VERSION applied; waiting up to $WAIT_READY s for it to report ready"
i=0
while [ "$i" -lt $((WAIT_READY * 2)) ]; do
    if [ -e "$STATE/ready-$VERSION" ]; then
        say "$VERSION is ready"
        exit 0
    fi
    i=$((i + 1))
    sleep 0.5
done

say "$VERSION did not report ready; putting the previous version back from $KEPT"
for pid in $(pgrep -f -- "$APP"); do  # what is left of the new version (never this script, whose arguments name it)
    [ "$pid" != "$$" ] && kill -9 "$pid" 2>/dev/null
done
rm -f "/var/tmp/velopack/$PACK/packages/"*"-$VERSION-"*.nupkg
printf '{"version": "%s", "reason": "it did not finish starting within %s seconds", "when": "%s"}\n' \
    "$VERSION" "$WAIT_READY" "$(date -Iseconds)" > "$STATE/rollback.json"
cp "$KEPT" "$APP.rollback" && chmod 755 "$APP.rollback" && mv -f "$APP.rollback" "$APP"
say "previous version restored (exit $?); starting it"
setsid "$APP" > /dev/null 2>&1 < /dev/null &
