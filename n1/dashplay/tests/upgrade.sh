#!/bin/bash
# Disposable overlay on the packaged image. Exercise apk's file/database operations
# independently for Core and LuCI without invoking init scripts on a build host.
set -euo pipefail
root=$1 work=$2 apks=$3
mkdir -p "$work"/{upgrade,upper,owork}
mount -t overlay overlay -o "lowerdir=$root,upperdir=$work/upper,workdir=$work/owork" "$work/upgrade"
trap 'umount "$work/upgrade"' EXIT
r=$work/upgrade
cp "$(command -v qemu-aarch64-static)" "$r/tmp/n1-qemu"
# This disposable chroot has neither a device filesystem nor a live netifd.
# Supply only the device and network snapshot fw4 and apk need for this test.
mkdir -p "$r/dev" "$r/tmp/run"
[ -c "$r/dev/null" ] || mknod -m 666 "$r/dev/null" c 1 3
mkdir -p "$r/proc"
printf 'Linux version 6.12.115-ophub\n' > "$r/proc/version"
for mode in on off; do
    cp "$work/firewall-$mode" "$r/etc/config/firewall"
    cat > "$r/tmp/run/fw4.state" <<'JSON'
{"networks":{"lan":{"up":true,"device":"eth0","physdev":"eth0","ipaddrs":[]},"carplay":{"up":true,"device":"br-carplay","physdev":"br-carplay","ipaddrs":[]}},"ubus_rules":[]}
JSON
    if [[ $mode == off ]]; then sed -i 's/,"carplay":{[^}]*}//' "$r/tmp/run/fw4.state"; fi
    ACTION=start chroot "$r" /tmp/n1-qemu /usr/bin/utpl -S /usr/share/firewall4/main.uc > "$work/fw4-$mode.nft"
done
grep -q dpncm "$work/fw4-on.nft"
grep -Eq 'br-carplay.*jump (input|forward)_carplay' "$work/fw4-on.nft"
grep -q 'jump input_carplay_usb' "$work/fw4-on.nft"
grep -Fq '/usr/share/n1-car/viewer.nft' "$work/fw4-on.nft"
if grep -Eq 'dpncm|usr/share/n1-car/viewer.nft' "$work/fw4-off.nft"; then exit 1; fi
echo 'Packaged fw4: car mode selects dpncm and native 443 rules; router mode selects neither.'
mkdir -p "$r/tmp/pkgtest" "$r/opt/dashplay/state" "$r/opt/dashplay/identity" "$r/etc/bluetooth/keys"
for f in opt/dashplay/state/n1-probe opt/dashplay/identity/n1-probe etc/bluetooth/keys/n1-probe; do
    echo offline-upgrade-fixture > "$r/$f"
done
config=$(sha256sum "$r/etc/config/dashplay")
cp "$apks"/*.apk "$r/tmp/pkgtest/"
: > "$r/tmp/pkgtest/repositories"
path=$(find "$r" -type f -name apk -print -quit); apk() { chroot "$r" /tmp/n1-qemu "${path#"$r"}" "$@"; }
args=()
for f in "$r"/tmp/pkgtest/*.apk; do args+=("/stage/${f##*/}"); done
bash "$(dirname "$0")/../host-apk.sh" "$r/tmp/pkgtest" mkndx --allow-untrusted -o /stage/packages.adb "${args[@]}"
for p in dashplay luci-app-dashplay luci-i18n-dashplay-zh-cn; do
    apk --no-network --repositories-file /tmp/pkgtest/repositories -X /tmp/pkgtest/packages.adb --allow-untrusted fix --no-scripts --reinstall "$p"
    for f in opt/dashplay/state/n1-probe opt/dashplay/identity/n1-probe etc/bluetooth/keys/n1-probe; do
        grep -qx offline-upgrade-fixture "$r/$f"
    done
    test "$config" = "$(sha256sum "$r/etc/config/dashplay")"
done
echo 'Independent APK reinstall: Core, LuCI and Chinese locale retain config / identity / state / Bluetooth keys (offline hooks disabled).'
