#!/bin/bash
set -euo pipefail
source_dir=$1 out=$(realpath "$2")
here=$(cd "$(dirname "$0")" && pwd)
shopt -s nullglob
images=("$source_dir"/*.img.gz)
[[ ${#images[@]} == 1 ]]
work=$(mktemp -d)
loop=''
cleanup() {
    mountpoint -q "$work/root" && umount "$work/root" || true
    mountpoint -q "$work/boot" && umount "$work/boot" || true
    [ -z "$loop" ] || losetup -d "$loop"
    rm -rf "$work"
}
trap cleanup EXIT
pigz -dc "${images[0]}" > "$work/image"
loop=$(losetup -fP --show "$work/image")
mkdir "$work/boot" "$work/root"
mount -o ro "${loop}p1" "$work/boot"
mount "${loop}p2" "$work/root"
test "$(blockdev --getsize64 "${loop}p2")" -ge $((2048 * 1024 * 1024))
bash "$here/finalize-root.sh" "$work/root" "$work/boot" "$out"
umount "$work/root"
umount "$work/boot"
losetup -d "$loop"
loop=''
mkdir -p "$out/n1-final"
pigz -n -p 4 -c "$work/image" > "$out/n1-final/immortalwrt-25.12.1-phicomm-n1-dashplay-6.12.115.img.gz"
