#!/bin/sh
base=/usr/libexec/n1-fast-kmods
fallback() { exec "$base/original" "$@"; }
[ "$(uname -r)" = '@KERNEL@' ] && [ -x /sbin/kmod ] || fallback "$@"
case "$#:$1" in
    0:|1:/etc/modules.d|1:/etc/modules.d/|1://etc/modules.d|1://etc/modules.d/) key=full; folder=/etc/modules.d ;;
    1:/etc/modules-boot.d|1:/etc/modules-boot.d/|1://etc/modules-boot.d|1://etc/modules-boot.d/) key=boot; folder=/etc/modules-boot.d ;;
    *) fallback "$@" ;;
esac
sum=$( { for f in "$folder"/*; do [ ! -f "$f" ] || sha256sum "$f"; done
    sha256sum /etc/modules.conf /lib/modules/@KERNEL@/modules.dep.bin; } | sha256sum)
read -r expected < "$base/$key.sha256" && [ "${sum%% *}" = "$expected" ] || fallback "$@"
if /bin/sh "$base/$key.sh"; then exit 0; fi
fallback "$@"
