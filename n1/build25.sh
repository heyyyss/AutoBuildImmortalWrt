#!/bin/bash
# Run inside immortalwrt/imagebuilder:armsr-armv8-openwrt-25.12.x.
set -euo pipefail

cd /home/build/immortalwrt
grep -q '^CONFIG_TARGET_armsr_armv8=y$' .config
grep -q '^CONFIG_USE_APK=y$' .config
grep -q '^CONFIG_TARGET_ARCH_PACKAGES="aarch64_generic"$' .config

source /n1/packages25.sh
mkdir -p packages files bin
cp -a /n1/files/. files/
build_log="$PWD/bin/n1-build-inputs.txt"
printf 'Architecture: aarch64_generic\nPassWall2: %s\nDocker: %s\n' \
    "${INCLUDE_PASSWALL2:-yes}" "${INCLUDE_DOCKER:-no}" > "$build_log"

# Fetch ONLY selected ARM64 APK directories, not the multi-GB whole repository.
apk_repo=$(mktemp -d)
trap 'rm -rf "$apk_repo"' EXIT
git -C "$apk_repo" init -q
git -C "$apk_repo" remote add origin https://github.com/wukongdaily/apk.git
git -C "$apk_repo" sparse-checkout init --cone
apk_dirs=(run/arm64/lucky run/arm64/rtp2httpd)
if [[ "${INCLUDE_PASSWALL2:-yes}" == yes ]]; then
    apk_dirs+=(run/arm64/passwall2 run/arm64/pwcore)
fi
git -C "$apk_repo" sparse-checkout set "${apk_dirs[@]}"
git -C "$apk_repo" -c protocol.version=2 fetch --depth=1 --filter=blob:none origin \
    "${APK_PACKAGES_REF:-5f58748c419c6091caac24ee425f47f389145d0c}"
git -C "$apk_repo" checkout -q --detach FETCH_HEAD
printf 'APK source: %s\n' "$(git -C "$apk_repo" rev-parse HEAD)" >> "$build_log"
for directory in "${apk_dirs[@]}"; do
    find "$apk_repo/$directory" -type f -name '*.apk' -exec cp {} packages/ \;
done

# Select actual APK release assets; never fall back to IPK.
download_release_apks() {
    local repository=$1 mode=$2 metadata asset_list url
    metadata=$(mktemp)
    asset_list=$(mktemp)
    if [[ "$mode" == latest ]]; then
        curl --fail --location --retry 3 "https://api.github.com/repos/$repository/releases/latest" -o "$metadata"
    else
        curl --fail --location --retry 3 "https://api.github.com/repos/$repository/releases?per_page=20" -o "$metadata"
    fi
    python3 - "$metadata" "$mode" > "$asset_list" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
releases = [data] if isinstance(data, dict) else data
for release in releases:
    if release.get('draft') or release.get('prerelease'):
        continue
    if sys.argv[2] == 'js' and not release['tag_name'].endswith('-js'):
        continue
    assets = [a['browser_download_url'] for a in release.get('assets', [])
              if a['name'].endswith('.apk')]
    if assets:
        print('\n'.join(assets))
        break
else:
    raise SystemExit('No compatible APK release assets found')
PY
    while IFS= read -r url; do
        curl --fail --location --retry 3 "$url" -o "packages/${url##*/}"
        printf '%s\n' "$url" >> "$build_log"
    done < "$asset_list"
    rm -f "$metadata" "$asset_list"
}

download_release_apks vernesong/OpenClash latest
download_release_apks ophub/luci-app-amlogic js

mkdir -p files/etc/openclash/core
core_archive=$(mktemp)
curl --fail --location --retry 3 \
    https://raw.githubusercontent.com/vernesong/OpenClash/core/master/meta/clash-linux-arm64.tar.gz \
    -o "$core_archive"
tar -xzOf "$core_archive" > files/etc/openclash/core/clash_meta
rm -f "$core_archive"
chmod 755 files/etc/openclash/core/clash_meta
# ELF e_machine=183 (AArch64), guarding against an accidental amd64 download.
python3 - <<'PY'
import struct
with open('files/etc/openclash/core/clash_meta', 'rb') as f:
    header = f.read(20)
assert header[:4] == b'\x7fELF' and header[4:6] == b'\x02\x01'
assert struct.unpack_from('<H', header, 18)[0] == 183, 'OpenClash core is not ARM64'
PY
for database in geoip geosite; do
    output=GeoIP
    [[ "$database" == geosite ]] && output=GeoSite
    curl --fail --location --retry 3 \
        "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/$database.dat" \
        -o "files/etc/openclash/$output.dat"
done

# Keep the ImageBuilder's OWN 25.12 config; the 24.10 n1/imm.config is incompatible.
# Only generate a rootfs archive: ophub supplies the N1 kernel, DTB and bootloader.
python3 - <<'PY'
from pathlib import Path
import re
p = Path('.config')
s = p.read_text()
settings = {
    'CONFIG_TARGET_ROOTFS_TARGZ': 'y',
    'CONFIG_TARGET_ROOTFS_CPIOGZ': None,
    'CONFIG_TARGET_ROOTFS_INITRAMFS': None,
    'CONFIG_TARGET_ROOTFS_EXT4FS': None,
    'CONFIG_TARGET_ROOTFS_SQUASHFS': None,
    'CONFIG_TARGET_IMAGES_GZIP': None,
}
for key, value in settings.items():
    s = re.sub(rf'^(?:{key}=.*|# {key} is not set)\n?', '', s, flags=re.M)
    s += f'{key}={value}\n' if value else f'# {key} is not set\n'
p.write_text(s)
# Normalize upstream APK names if a commit hash uses '.' instead of '~'.
for apk in Path('packages').glob('*.apk'):
    name = re.sub(r'\.([a-f0-9]{7}\.apk)$', r'~\1', apk.name)
    if name != apk.name:
        apk.rename(apk.with_name(name))
PY

PACKAGES=$(printf '%s\n' "$N1_PACKAGES" | tr ' ' '\n' | sed '/^$/d' | sort -u | tr '\n' ' ')
printf 'Requested packages: %s\n' "$PACKAGES" | tee -a "$build_log"
sha256sum packages/*.apk files/etc/openclash/core/clash_meta >> "$build_log"
make image PROFILE=generic PACKAGES="$PACKAGES" FILES="$PWD/files"

shopt -s nullglob
rootfs=(bin/targets/armsr/armv8/*generic-targz-rootfs.tar.gz)
if [[ ${#rootfs[@]} -eq 0 ]]; then
    rootfs=(bin/targets/armsr/armv8/*generic-rootfs.tar.gz)
fi
[[ ${#rootfs[@]} -eq 1 ]] || { echo 'Missing or ambiguous generic rootfs archive' >&2; exit 1; }
tar -tzf "${rootfs[0]}" > bin/n1-rootfs-files.txt
grep -Eq '^(\./)?etc/uci-defaults/zz-n1-dhcp$' bin/n1-rootfs-files.txt
printf '%s\n' "${rootfs[0]}" > bin/n1-rootfs-path.txt
echo 'N1 ARM64 rootfs build complete.'
