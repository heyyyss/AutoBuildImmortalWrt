# N1 / ImmortalWrt 25.12 / DHCP

**使用 DashPlay 分支时**，请先读[车载开关、固件与独立 APK 升级说明](dashplay/README.md)。下面保留的是普通 `n1-25-dhcp` 基线的构建记录。

分支：`n1-25-dhcp`。以 `origin/heyyyss-patch-1` 的 `f704335` 为基础，参考之前的 x86 25.12.1，新增独立的 N1 25 构建入口。

2026-11-03，[构建 #2 已成功](https://github.com/heyyyss/AutoBuildImmortalWrt/actions/runs/41656072434)，对应固件代码 `503fa33`。ARM64 rootfs、N1 打包和最终镜像校验均通过。下载 Artifacts 中的 `immortalwrt-25.12.1-phicomm-n1-dhcp-2`（约 326 MB，保留 30 天）；尚未进行 N1 实机启动测试。

## 构建与网络

- 工作流：`.github/workflows/build-N1-25.12.x.yml`，名称 **Build 25.12.x N1 DHCP**。
- 向本分支推送构建文件会自动运行，也可以手动选择版本、内核、PassWall2、Docker 和分区大小。
- 默认 ImmortalWrt **25.12.1**、ophub stable **6.12.y** 最新补丁、rootfs **1024 MiB**、PassWall2 **yes**、Docker **no**。
- 单网口 `eth0` 为 DHCP 客户端，地址、默认网关、DNS 均向上级路由器获取；主机名 `ImmortalWrt-N1`。
- 关闭 N1 的 DHCPv4 服务、DHCPv6 服务和 IPv6 RA；删除残留 WAN/PPPoE 接口及静态 IPv4 地址。
- 从上级路由器的 DHCP 租约列表查找管理地址，建议在上级为 N1 设置固定租约。**不会固定使用之前 x86 的 192.168.3.1**。
- 管理入口处于受信任的上级 LAN；这个默认配置不适合直接把单网口接入公网。
- DHCP 客户端模式只保证 N1 自己能上网。其他设备要走 N1 的 OpenClash，需要另外设置这些设备的网关、DNS 或上级路由策略。

工作流产物在对应 Actions 运行页的 Artifacts，包含 `.img.gz`、SHA-256、软件包输入记录和验证报告。与 x86 的 EFI / ESXi VMDK 不通用；这是带 N1 DTB 和启动文件的实体盒子镜像。先写 U 盘进行实机启动验证，再考虑写入 eMMC。

## 与 x86 25 版和旧 N1 24 版的区别

| 项目 | x86 25 版 | 本分支 N1 25 版 |
| --- | --- | --- |
| 用户空间 | x86_64 / APK | aarch64_generic / APK，N1 为 Cortex-A53 |
| ImageBuilder | x86-64 | armsr-armv8；保留官方 25 版配置，不加载旧 N1 24 的完整 `.config` |
| 第三方二进制 | `run/x86`、amd64 OpenClash | 只取选中功能的 `run/arm64` APK、arm64 OpenClash |
| 系统镜像 | squashfs EFI / ESXi | ophub 打包 `s905d`，Btrfs rootfs、N1 DTB、专用内核和启动文件 |
| 网络 | 多口 LAN/WAN，静态管理 IP | 单口 LAN DHCP 客户端，无 DHCP 服务 |
| 内存规划 | 之前设备为 16GB | N1 为 2GB；Docker 默认不集成 |
| eMMC 安装管理 | 无需晶晨工具 | 集成晶晨宝盒及安装脚本所需工具 |

旧 `.github/workflows/build-N1.yml` 仍为 24.10/IPK，只作为历史入口；本分支不更改它，也不修改 x86 的插件清单和共享 `99-custom.sh`。N1 用 `n1/files` 独立覆盖目录。

## 插件选择与限制

“保留”表示本分支请求集成；是否成功以本次 APK 依赖解析和最终镜像验证为准，不能据此宣称已实机测试。

| 功能 | 本分支选择 | N1 使用条件 / 原因 |
| --- | --- | --- |
| OpenClash | 保留 | 下载 ARM64 核心并校验 ELF 架构；检查最终内核的 TUN、TPROXY、socket 支持。吞吐和规则规模受 N1 性能限制 |
| PassWall2 | 默认集成，可关闭 | 使用 ARM64 APK 和依赖；作为备用，不与 OpenClash 同时启用透明代理 |
| Lucky | 保留 | 使用 APK 仓库的 ARM64 Lucky；DDNS、反代等按需要开启；不要与 DDNS-Go 更新同一记录 |
| DDNS-Go | 保留 | ARM64 可用；无公网入站条件时，配置 DDNS 不会自动打通外网访问 |
| Tailscale | 保留 | 社区 LuCI 界面；实际连接需登录并检查 TUN；不用为此再集成 OpenVPN |
| WireGuard | 保留 UI 和工具 | 最终打包内核必须提供 WireGuard；直连入站条件仍需满足 |
| RTP2HTTPD | 保留 | ARM64 包；IPTV 是否可用取决于上游组播/VLAN与网络接法 |
| WOL / 定时 WOL | 保留 | 目标设备需支持网络唤醒 |
| ARP 绑定 | 保留 UI | 只影响 N1 本地邻居表，不代替上级路由器的 DHCP 固定租约 |
| nlbwmon | 保留 | 只统计经过 N1 的流量，不能看到同网段所有设备直接访问上级的流量 |
| Argon、终端、SFTP、文件管理、uhttpd 设置 | 保留 | 管理功能；文件管理不等于 Samba/NFS 共享 |
| 晶晨宝盒 | 新增 | N1 安装、升级相关；内核和模块来自 ophub，不能混装官方 armsr kmod |
| Docker | 默认不选，可开启 | 可以使用 ARM64 容器；须检查最终内核支持，建议外置盘放数据并控制内存占用；amd64 镜像不能当作原生 ARM64 镜像运行 |
| QuickStart / iStore | 不选 | 避免自动引入商店及额外管理依赖；之前你没有要求 N1 必装 |
| QuickFile / Samba / NFS | 不选 | 已有 NAS；路由器保留轻量文件管理即可 |
| Bandix | 不选 | ARM64 APK 存在，但此版减少常驻监控开销；可后续单独评估 |
| SQM | 不选 | DHCP 单口接在上级 LAN，不是默认的出口整形位置；不是 ARM64 不支持 |
| Partexp | 不选 | 不直接照搬 x86 分区扩容插件，使用 N1 打包和晶晨工具管理存储 |
| AppFilter / oaf | 不选 | 需要专用内核模块；不能把官方 armsr 或 x86 模块装到 ophub 内核上 |
| Nikki / SSR Plus | 不选 | 存在 ARM64 包，但已有 OpenClash 和 PassWall2，避免重复安装更多透明代理 |
| vlmcsd | 不选 | 最新 x86 清单也未启用，当前用途不需要；没有宣称 ARM64 无法运行 |
| macc / Fancyss 链接中的软件 | 不预装 | 需要供应方明确支持 OpenWrt 25 APK、aarch64_generic 及当前内核；x86 包不能复用 |

## 内核兼容性和验收

ophub 会删除 ImageBuilder 的 `/lib/modules/*` 并替换成匹配的 N1 内核模块。插件的 LuCI 页面能打开，不代表其内核功能可用。AppFilter 这类额外模块不能仅靠复制插件移植；也不能刷机后直接从官方 armsr 源安装 kmod 来“补驱动”。

`n1/verify-image.sh` 在发布构建产物前挂载**最终 N1 镜像**，检查：

1. 25.12 版本、OpenClash ARM64 ELF、N1 DTB 和启动配置。
2. 最终内核配置、模块版本及 TUN、NFT TPROXY/socket、WireGuard；选 Docker 时附加容器相关能力检查。
3. 用最终镜像内的真实 UCI 二进制经 QEMU，在配置副本上执行 DHCP 首启脚本；确认删除静态/PPPoE 残留、不发 DHCP/RA、重复执行结果一致。

这些检查不能代替 N1 实机冷启动、以太网/Wi-Fi、USB、代理速度或 eMMC 写入测试。不要使用 x86 的 VMDK 或直接把通用 ARM EFI 镜像当 N1 镜像刷入。

## 上游依据

- [ImmortalWrt 25.12.1 ARMv8 下载目录](https://downloads.immortalwrt.org/releases/25.12.1/targets/armsr/armv8/)
- [ophub 打包流程](https://github.com/ophub/amlogic-s9xxx-openwrt/blob/c7578a7699ad2c002eca81e4b131b5c73c708845/remake)
- [N1 设备定义](https://github.com/ophub/amlogic-s9xxx-openwrt/blob/c7578a7699ad2c002eca81e4b131b5c73c708845/make-openwrt/openwrt-files/common-files/etc/model_database.conf)
- [ARM64 APK 清单](https://github.com/wukongdaily/apk/tree/5f58748c419c6091caac24ee425f47f389145d0c/run/arm64)
- [OpenClash ARM64 内核](https://github.com/vernesong/OpenClash/tree/core/master/meta)
