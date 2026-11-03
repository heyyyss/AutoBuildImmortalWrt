#!/bin/bash
# Verify the PACKAGED image, not just the generic rootfs before kernel replacement.
set -euo pipefail
source_dir=${1:?Packager output directory required}
output_dir=${2:?Build output directory required}
mkdir -p "$output_dir/n1-firmware"
output_dir=$(realpath "$output_dir")
shopt -s nullglob
images=("$source_dir"/*.img.gz)
[[ ${#images[@]} -eq 1 ]] || { echo 'Expected exactly one N1 image' >&2; exit 1; }
work=$(mktemp -d)
loop=''
cleanup() {
    mountpoint -q "$work/root" && umount "$work/root" || true
    mountpoint -q "$work/boot" && umount "$work/boot" || true
    [[ -z "$loop" ]] || losetup -d "$loop"
    rm -rf "$work"
}
trap cleanup EXIT
gzip -dc "${images[0]}" > "$work/n1.img"
loop=$(losetup --find --show --partscan "$work/n1.img")
mkdir "$work/root" "$work/boot"
mount -o ro "${loop}p1" "$work/boot"
mount -o ro "${loop}p2" "$work/root"
export N1_VERIFY_ROOT="$work/root"

report="$output_dir/n1-firmware/verification.txt"
python3 - "$work/root" "$work/boot" <<'PY' | tee "$report"
from pathlib import Path
import os, re, struct, sys
root, boot = map(Path, sys.argv[1:])
release = (root / 'etc/openwrt_release').read_text()
assert re.search(r"DISTRIB_RELEASE=['\"]25\.12\.", release), release
core = root / 'etc/openclash/core/clash_meta'
header = core.open('rb').read(20)
assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183
defaults = root / 'etc/uci-defaults/zz-n1-dhcp'
assert defaults.is_file() and os.access(defaults, os.X_OK)
assert not (root / 'etc/uci-defaults/99-custom.sh').exists(), 'Shared x86 network script included'
boot_config = (boot / 'uEnv.txt').read_text()
dtb = 'meson-gxl-s905d-phicomm-n1.dtb'
assert dtb in boot_config and (boot / 'dtb/amlogic' / dtb).is_file()
configs = list(boot.glob('config-*'))
assert len(configs) == 1, 'Missing or ambiguous packaged kernel config'
kernel_config = configs[0].read_text()
required = ['TUN', 'NFT_TPROXY', 'NFT_SOCKET', 'NF_TPROXY_IPV4',
            'NF_TPROXY_IPV6', 'WIREGUARD']
if os.environ.get('INCLUDE_DOCKER', 'no') == 'yes':
    required += ['CGROUPS', 'NAMESPACES', 'NET_NS', 'VETH', 'BRIDGE', 'OVERLAY_FS']
modules = root / 'lib/modules'
versions = [p.name for p in modules.iterdir() if p.is_dir()]
assert len(versions) == 1, f'Unexpected kernel module directories: {versions}'
assert configs[0].name == 'config-' + versions[0], 'Kernel config/module version mismatch'
module_names = {'TUN': 'tun', 'NFT_TPROXY': 'nft_tproxy', 'NFT_SOCKET': 'nft_socket',
                'NF_TPROXY_IPV4': 'nf_tproxy_ipv4', 'NF_TPROXY_IPV6': 'nf_tproxy_ipv6',
                'WIREGUARD': 'wireguard', 'VETH': 'veth', 'BRIDGE': 'bridge',
                'OVERLAY_FS': 'overlay'}
for name in required:
    match = re.search(rf'^CONFIG_{name}=([ym])$', kernel_config, re.M)
    assert match, f'Packaged kernel does not support CONFIG_{name}'
    if match[1] == 'm' and name in module_names:
        assert list(modules.rglob(module_names[name] + '.ko*')), f'Missing module: {name}'
    print(f'CONFIG_{name}={match[1]}: OK')
print('ImmortalWrt 25.12 release: OK')
print('OpenClash AArch64 core: OK')
print('N1 DTB and boot config: OK')
print('Matching kernel/modules:', versions[0])
PY

# Run the actual first-boot script using the image's ARM64 UCI binary under QEMU.
# Use copies of the configs so the image stays unchanged.
export N1_UCI_BINARY
N1_UCI_BINARY=$(find "$work/root" -path '*/uci' -type f | head -n 1)
test -n "$N1_UCI_BINARY"
export N1_UCI_CONFIG="$work/config" N1_UCI_TEMP="$work/uci-tmp"
mkdir -p "$N1_UCI_CONFIG" "$N1_UCI_TEMP" "$work/bin"
cp -a "$work/root/etc/config/." "$N1_UCI_CONFIG/"
touch "$N1_UCI_CONFIG/network" "$N1_UCI_CONFIG/dhcp" \
    "$N1_UCI_CONFIG/system" "$N1_UCI_CONFIG/firewall"
cat > "$work/bin/uci" <<'SH'
#!/bin/sh
exec qemu-aarch64-static -L "$N1_VERIFY_ROOT" "$N1_UCI_BINARY" \
    -c "$N1_UCI_CONFIG" -t "$N1_UCI_TEMP" "$@"
SH
chmod +x "$work/bin/uci"
export PATH="$work/bin:$PATH"
if ! uci -q get 'system.@system[0]' >/dev/null; then
    uci add system system >/dev/null
    uci commit system
fi
# Seed the conflicting static/dual-port settings that the N1 script must remove.
uci set network.lan=interface
uci set network.lan.proto=static
uci set network.lan.ipaddr=192.168.3.1
uci set network.lan.gateway=192.168.3.254
uci set network.wan=interface
uci set network.wan.proto=pppoe
uci set network.wan6=interface
uci set network.wan6.proto=dhcpv6
uci commit network
sh "$work/root/etc/uci-defaults/zz-n1-dhcp"
test "$(uci get network.lan.proto)" = dhcp
test "$(uci get network.lan.device)" = eth0
test "$(uci get network.lan.peerdns)" = 1
test "$(uci get network.lan.defaultroute)" = 1
for option in network.lan.ipaddr network.lan.gateway network.wan network.wan6; do
    if uci -q get "$option" >/dev/null; then
        echo "Unexpected static/WAN option remains: $option" >&2
        exit 1
    fi
done
test "$(uci get dhcp.lan.ignore)" = 1
test "$(uci get dhcp.lan.ra)" = disabled
test "$(uci get dhcp.lan.dhcpv6)" = disabled
test "$(uci get dhcp.lan.ndp)" = disabled
first=$(sha256sum "$N1_UCI_CONFIG"/*)
sh "$work/root/etc/uci-defaults/zz-n1-dhcp"
test "$first" = "$(sha256sum "$N1_UCI_CONFIG"/*)"
printf 'DHCP client / no DHCP server / no IPv6 RA: OK\nFirst-boot script idempotence: OK\nHardware boot test: not performed\n' | tee -a "$report"

cp "${images[0]}" "$output_dir/n1-firmware/"
cd "$output_dir/n1-firmware"
sha256sum ./*.img.gz > SHA256SUMS
