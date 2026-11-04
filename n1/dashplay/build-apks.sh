#!/usr/bin/env bash
# Linux + Docker. The SDK builds the core and LuCI APKs; the pinned JRE is reused.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(realpath -m "${1:?output directory}")
source "$here/revisions.env"
release=${N1_CORE_RELEASE:?}
ui_release=${N1_LUCI_RELEASE:?}
[[ $release =~ ^[1-9][0-9]*$ && $ui_release =~ ^[1-9][0-9]*$ ]] || exit 2
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT
if [[ -n ${N1_FEED:-} ]]; then
    cp -a "$N1_FEED" "$temp/feed"
else
    git init -q "$temp/feed"
    git -C "$temp/feed" fetch -q --depth=1 https://github.com/yizhixiaoheigou/openwrt-dashplay f6d20b93a9aa2241f8833c7277e5c24a54b91f52
    git -C "$temp/feed" checkout -q --detach FETCH_HEAD
fi
python3 "$here/prepare-feed.py" "$temp/feed" "$release" "$ui_release"
mkdir -p "$out" "$temp/dl"
if [[ -n ${N1_BUNDLE:-} ]]; then
    bundle=$(sed -n 's/^PKG_VERSION:=//p' "$temp/feed/dashplay/Makefile")
    cp "$N1_BUNDLE" "$temp/dl/dashplay-bundle-$bundle.tar"
    hash=$(sha256sum "$N1_BUNDLE" | cut -d' ' -f1)
    sed -i "s/^PKG_HASH:=.*/PKG_HASH:=$hash/" "$temp/feed/dashplay/Makefile"
fi
chmod 755 "$temp"; chmod -R a+rX "$temp/feed" "$temp/dl"
mkdir -m 777 "$temp/out"
docker run --rm --cap-drop ALL --security-opt no-new-privileges \
    -v "$temp/feed:/feed:ro" -v "$temp/dl:/local:ro" -v "$temp/out:/out" \
    --entrypoint sh "${OPENWRT_SDK:-openwrt/sdk:x86-64-25.12.5}" -ec '
    cd /builder
    echo "src-link dashplay /feed" >> feeds.conf.default
    ./scripts/feeds update luci dashplay
    ./scripts/feeds install -p dashplay -a
    make defconfig >/dev/null
    mkdir -p dl
    cp /local/*.tar dl/ 2>/dev/null || true
    make package/dashplay/compile package/luci-app-dashplay/compile V=s
    cp bin/packages/*/dashplay/dashplay-2*.apk bin/packages/*/dashplay/luci-*.apk /out/'
cp "$temp"/out/*.apk "$out/"
jre=dashplay-jre-21.0.12.1-r3_aarch64_generic.apk
curl -fLsS --retry 3 "https://github.com/yizhixiaoheigou/openwrt-dashplay/releases/download/v2026.11.02/$jre" -o "$out/$jre"
(cd "$out" && echo "3a106271dde5a3e9cdc0fe4dbd21e03ced39cb406e1a6acec8f1a9f30ac93ee8  $jre" | sha256sum -c -)
