#!/bin/bash
# Called on the mounted final Btrfs/boot partitions, before producing the deliverable.
set -euo pipefail
root=$1 boot=$2 out=$3
here=$(cd "$(dirname "$0")" && pwd)
kernel=6.12.115-ophub
modules="$root/lib/modules/$kernel"
cfg="$boot/config-$kernel"
test -s "$cfg"; test -d "$modules"
for k in BT BT_BREDR BT_HCIUART BT_HCIUART_BCM BT_RFCOMM; do
    grep -Eq "^CONFIG_${k}=[ym]$" "$cfg"
done
for mod in bluetooth hci_uart btbcm rfcomm; do
    file="$modules/$mod.ko"
    test -s "$file"
    [[ $(modinfo -F vermagic "$file") == "$kernel "* ]]
done
fw="$root/lib/firmware/brcm"
test -s "$fw/BCM4345C0.hcd"
wifi="$root/lib/netifd/wireless/mac80211.sh"
# Restore only a proved, unmodified backup of the specific ophub transformation.
grep -q 'iw ' "$wifi.bak"
grep -q 'ucode' "$wifi.bak"
cmp -s <(sed 's/iw /ipconfig /g' "$wifi.bak") "$wifi"
cp -p "$wifi.bak" "$wifi"
test -x "$wifi" && ! grep -q 'ipconfig ' "$wifi"
for ext in bin txt clm_blob; do
    target=brcmfmac43455-sdio.phicomm,n1.$ext
    [ -s "$fw/$target" ] || ln -sfn "brcmfmac43455-sdio.$ext" "$fw/$target"
    test -s "$fw/$target"
done
ln -sfn brcmfmac43455-sdio.clm_blob "$fw/brcmfmac43455-sdio.phicomm,n1.clm_blob"
# Make the board copy independent of generic firmware/NVRAM files. Its address is
# individualized on first enable; the AP also has an explicit, persistent MAC.
nv="$fw/brcmfmac43455-sdio.phicomm,n1.txt"
cp -L "$nv" "$nv.n1"
mv -fT "$nv.n1" "$nv"
# Offline target apk sees its own database. Do not run online package hooks under the CI kernel.
qemu=$(command -v qemu-aarch64-static)
cp "$qemu" "$root/tmp/n1-qemu"
target() { chroot "$root" /tmp/n1-qemu "$@"; }
apkpath=$(find "$root" -name apk -type f | head -1)
apkpath=${apkpath#"$root"}
work=/tmp/n1-bt
mkdir -p "$root$work/data/etc/modules.d"
printf 'hci_uart\nrfcomm\n' > "$root$work/data/etc/modules.d/90-n1-bluetooth"
cat > "$root$work/pre" <<'SH'
#!/bin/sh
set -eu
[ "$(uname -r)" = '6.12.115-ophub' ]
for mod in hci_uart btbcm bluetooth rfcomm; do modinfo "$mod" >/dev/null; done
test -s /lib/firmware/brcm/BCM4345C0.hcd
SH
provider=carplay-ophub-bluetooth-6.12.115-r3.apk
target "$apkpath" mkpkg -I name:carplay-ophub-bluetooth -I version:6.12.115-r3 \
    -I arch:aarch64_generic -I description:'Verified preinstalled ophub Bluetooth modules' \
    -I license:GPL-2.0-only -I depends:kernel -I provides:kmod-bluetooth=6.12.115-r1 \
    -s "pre-install:$work/pre" -F "$work/data" -o "$work/$provider"
cp "$root$work/$provider" "$out/n1-apks/"
cp "$out"/n1-bluez/*.apk "$root$work/"
args=()
for p in "$root$work"/*.apk; do args+=("$work/${p##*/}"); done
apk_offline() { target "$apkpath" --no-network --repositories-file /dev/null "$@"; }
apk_offline --allow-untrusted --no-scripts add "${args[@]}"
apk_offline info -e bluez-daemon bluez-utils bluez-utils-extra carplay-ophub-bluetooth
if apk_offline info --installed | grep -q '^kmod-bluetooth-'; then echo 'Unexpected armsr Bluetooth modules' >&2; exit 1; fi
# BlueZ is started at 19 only for car mode; dbus remains a shared system service.
rm -f "$root"/etc/rc.d/S*bluetoothd
for item in '18 n1-car-bus' '19 n1-car-bt' '21 dashplay'; do
    read -r order service <<< "$item"
    rm -f "$root"/etc/rc.d/S*"$service"
    ln -s "../init.d/$service" "$root/etc/rc.d/S$order$service"
done
test -e "$root/etc/modules.conf" || touch "$root/etc/modules.conf"
test -s "$modules/modules.dep.bin" || depmod -b "$root" "$kernel"
python3 "$here/fast-plan.py" "$root" "$kernel"
target /usr/bin/python3 -c 'import sys; assert sys.version_info >= (3,11); import ssl, ctypes'
# The installed JRE path comes from the package itself.
target /usr/lib/dashplay-jre/bin/java -Xint -Xmx32m -version 2>&1 | grep '21\.0\.'
target /usr/libexec/carplay-compat/btmgmt --version
target /usr/bin/python3 /opt/dashplay/supervisor_openwrt.py --root /opt/dashplay --check
apk_offline list --installed > "$out/n1-final-packages.txt"
rm -rf "$root$work" "$root/tmp/n1-qemu"
# No per-device state is made while packaging; reject loaded keys or identities.
for d in etc/bluetooth/keys etc/n1-car opt/dashplay/state opt/dashplay/identity; do
    [[ ! -d "$root/$d" || -z "$(find "$root/$d" -type f -print -quit)" ]] || { echo "Private state: $d"; exit 1; }
done
