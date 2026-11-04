#!/bin/bash
# Sourced inside the ImageBuilder, before make image.
set -euo pipefail
out=$PWD/bin/n1-apks
work=$(mktemp -d)
cp -a /n1/dashplay/support "$work/support"
compat="$work/support/usr/libexec/carplay-compat"
mkdir -p "$compat"
ipk=bluez-utils-extra_5.72-r2_aarch64_generic.ipk
curl -fsSL --retry 3 "https://downloads.openwrt.org/releases/24.10.4/packages/aarch64_generic/packages/$ipk" -o "$work/$ipk"
echo "25466107142ded571eb2e90a03b157768270e1f12ea014f943f7049a2e0bac26  $work/$ipk" | sha256sum -c -
tar -xzOf "$work/$ipk" ./data.tar.gz | tar -xzOf - ./usr/bin/btmgmt > "$compat/btmgmt"
echo "6b99656d72278c91851e0037f9c109f7ab0492f2115586725bdb8e538992b450  $compat/btmgmt" | sha256sum -c -
chmod 755 "$compat/btmgmt"
apkhost=$PWD/staging_dir/host/bin/apk
"$apkhost" mkpkg -I name:n1-car-support -I version:1.0-r1 -I arch:aarch64_generic \
    -I description:'Phicomm N1 car mode, Bluetooth tool and TLS watcher' \
    -I license:GPL-2.0-or-later -I depends:'python3' -F "$work/support" -o "$out/n1-car-support-1.0-r1.apk"
cp "$out"/*.apk packages/
rm -rf "$work"
N1_PACKAGES+=" dashplay luci-app-dashplay luci-i18n-dashplay-zh-cn n1-car-support dashplay-jre"
# All BlueZ userspace deps except bluez-libs (it requests an armsr kmod).
N1_PACKAGES+=" dbus libical glib2 libreadline libncurses python3 openssl-util ca-certificates"
