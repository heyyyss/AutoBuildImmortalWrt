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
for mode in on off; do
    cp "$work/firewall-$mode" "$r/etc/config/firewall"
    ACTION=print chroot "$r" /tmp/n1-qemu /usr/bin/utpl -S /usr/share/firewall4/main.uc > "$work/fw4-$mode.nft"
done
grep -q dpncm "$work/fw4-on.nft"
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
path=$(find "$r" -type f -name apk -print -quit); apk() { chroot "$r" /tmp/n1-qemu "${path#"$r"}" "$@"; }
args=()
for f in "$r"/tmp/pkgtest/*.apk; do args+=("/stage/${f##*/}"); done
bash "$(dirname "$0")/../host-apk.sh" "$r/tmp/pkgtest" mkndx --allow-untrusted -o /stage/packages.adb "${args[@]}"
for p in dashplay luci-app-dashplay luci-i18n-dashplay-zh-cn; do
    apk --no-network --repositories-file /dev/null -X /tmp/pkgtest/packages.adb --allow-untrusted fix --no-scripts --reinstall "$p"
    for f in opt/dashplay/state/n1-probe opt/dashplay/identity/n1-probe etc/bluetooth/keys/n1-probe; do
        grep -qx offline-upgrade-fixture "$r/$f"
    done
    test "$config" = "$(sha256sum "$r/etc/config/dashplay")"
done
echo 'Independent APK reinstall: Core, LuCI and Chinese locale retain config / identity / state / Bluetooth keys (offline hooks disabled).'
