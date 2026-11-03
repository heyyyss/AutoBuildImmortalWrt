#!/bin/bash
# N1 / ImmortalWrt 25.12: aarch64_generic APKs only.
# Keep this separate from the x86 package selection.
N1_PACKAGES="bash curl ca-bundle ip-full unzip jq"
N1_PACKAGES+=" luci luci-i18n-base-zh-cn luci-compat"
N1_PACKAGES+=" luci-theme-argon luci-app-argon-config luci-i18n-argon-config-zh-cn"
N1_PACKAGES+=" luci-i18n-firewall-zh-cn luci-i18n-package-manager-zh-cn"
N1_PACKAGES+=" luci-i18n-ttyd-zh-cn luci-i18n-uhttpd-zh-cn openssh-sftp-server"
N1_PACKAGES+=" luci-i18n-filemanager-zh-cn"
N1_PACKAGES+=" luci-app-openclash kmod-tun kmod-inet-diag kmod-nft-tproxy"
N1_PACKAGES+=" lucky luci-app-lucky luci-i18n-lucky-zh-cn"
N1_PACKAGES+=" luci-app-tailscale-community luci-i18n-tailscale-community-zh-cn"
N1_PACKAGES+=" luci-i18n-ddns-go-zh-cn luci-proto-wireguard wireguard-tools"
N1_PACKAGES+=" luci-i18n-wol-zh-cn luci-i18n-timewol-zh-cn"
N1_PACKAGES+=" luci-i18n-arpbind-zh-cn luci-i18n-nlbwmon-zh-cn"
N1_PACKAGES+=" rtp2httpd luci-app-rtp2httpd luci-i18n-rtp2httpd-zh-cn"
# Required by the N1 packaging / eMMC installation tools.
N1_PACKAGES+=" luci-app-amlogic luci-i18n-amlogic-zh-cn"
N1_PACKAGES+=" block-mount blkid btrfs-progs e2fsprogs fdisk lsblk losetup"
N1_PACKAGES+=" parted dosfstools resize2fs tune2fs uuidgen mount-utils tar gzip"
N1_PACKAGES+=" kmod-brcmfmac wpad-basic-mbedtls iw iwinfo"
N1_PACKAGES+=" perlbase-base perlbase-file perlbase-time perlbase-utf8 perlbase-xsloader"

if [[ "${INCLUDE_PASSWALL2:-yes}" == yes ]]; then
    N1_PACKAGES+=" luci-app-passwall2 luci-i18n-passwall2-zh-cn"
    N1_PACKAGES+=" geoview xray-core sing-box hysteria kmod-nft-socket"
fi

if [[ "${INCLUDE_DOCKER:-no}" == yes ]]; then
    N1_PACKAGES+=" luci-i18n-dockerman-zh-cn"
fi

# Not selected: iStore / QuickStart, QuickFile / NAS services, Bandix,
# SQM, AppFilter, Nikki, SSR Plus, OpenVPN and vlmcsd.
# The ophub packager replaces ALL ImageBuilder kernel modules. Never install
# armsr kmods later on the N1; use the matching ophub kernel/modules instead.
