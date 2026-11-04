# N1 DashPlay USB 固件

基于 `n1-25-dhcp` 的 25.12.1，保留 OpenClash、Lucky、DDNS-Go、WireGuard、Tailscale、LuCI/SSH 等旁路由组件。此配置不预装 PassWall2 和 Docker。专用镜像固定 ophub 6.12.115、N1 DTB 和 2048 MiB 根分区，仅适合实体 N1；先用另一只 U 盘验证。

[完整构建 #3](https://github.com/heyyyss/AutoBuildImmortalWrt/actions/runs/41808136465) 对应运行时代码 `0eda0cf`。完整产物包含 USB 镜像、成品验证报告、校验和，以及 Core 2026.11.02-r2、LuCI 和中文包 0.261102.35991-r3。该镜像已在 N1 从 U 盘启动，iPad 已实测有线及无线 CarPlay。

## 开关和首次使用

在 **服务 → DashPlay → Network（网络）→ 车载模式** 保存并应用，或通过 SSH 执行：

```sh
n1-car-mode status
n1-car-mode off
n1-car-mode on
```

两种模式的有线管理入口都在上级路由的 DHCP 租约里找。N1 不在 eth0 发 DHCP、RA，也不固定占用 192.168.3.1。若要让家庭设备走 N1 的代理，仍需在上级或指定客户端配置网关/DNS。

车载模式默认开启。首次从 eth0 登录后，在 LuCI 无线页面查看本机生成的热点密码，或在自己的 SSH 会话执行 `uci -q get wireless.n1_car.key`。热点 `DashPlay-N1` 使用独立的 `br-carplay`、100.96.0.1/24、WPA2/CCMP 和独立 DHCP；默认按已实测的 CN/149/VHT20 配置，其他地区需按当地可用信道调整配置源。Wi-Fi AP 地址和密码按设备生成并跨开关保留。Tailscale 与 Tesla 热点的地址范围重叠，使用 Tesla 模式时先不要开启 Tailscale。USB 动态接口 dpncm 仅放行本机输入输出，不对家庭 LAN 转发。

打开时 LuCI HTTP 管理保留，观看服务直接监听 HTTPS 443，旧 65367 只转发本机目标流量。关闭时停止接收端和车载专用蓝牙，撤销热点、地址池、上行 NAT 和车载防火墙规则，归还之前的无线设置及 LuCI HTTPS 监听；证书任务直接退出。设置页在热点内是 `http://100.96.0.1:18080/`。浏览器观看使用自己配置的域名。认证身份、DuckDNS 账号、证书和配对均需在设备上配置；公共镜像不含这些数据。应用升级保留状态和身份，系统备份含有私密材料，请自行保管。

从 `n1-car-support 1.0-r3` 起，iPhone 开启「个人热点 → 允许其他人加入」并插入 N1 后，同一根线可传有线 CarPlay 并为热点供网。iPad 或车机继续连接 `DashPlay-N1`。家庭网线和手机都可用时，默认优先使用家庭网线。USB 接口 `iphone_usb` 通过 DHCP 获取地址，只有车载热点获准向它转发；关闭车载模式会撤销这些规则。

拔线后无线 CarPlay 可以接手。若插回的是本次开机以来已同时提供过有线 CarPlay 和外网的同一部手机，共享已开启但 USB 链路仍未就绪，支持包会通过 DashPlay 将会话切回有线。只用无线、多个已配对手机、不同手机或 USB 已正常供网时，支持包不会发起这个切换。手机识别记录只保存在本次开机的内存目录里。2026-11-04 在构建 #3 的 U 盘上实测了重启及同一部 iPhone 实际拔插，iPad 的外网和 CarPlay 画面、触控均自动恢复。r3 的整机镜像留待下次构建。

## 独立升级和二次开发

- **只改 LuCI 或翻译**：用自己的 OpenWrt feed，更改 `luci-app-dashplay/`，提升 `revisions.env` 中 LuCI 的修订号，仅安装新 UI APK（如修改翻译，再装中文 APK）。
- **改接收端**：按 DashPlay 上游工具生成新 bundle；用 `N1_BUNDLE` 指向该文件，提升 Core 修订号。脚本会把实际 SHA256 写入临时 SDK 配方。开放 443 的补丁及服务入口会在打包时应用；若上游结构变化，脚本明确失败，需先复核。
- **改内核、固件或快速加载计划**：重新构建整镜像。不要在设备上直接升级 armsr 的内核模块，亦不要使用上游的一键更新覆盖 N1 定制包。

Linux + Docker 本地示例（从仓库根目录）：

```sh
N1_FEED=/path/to/openwrt-dashplay N1_BUNDLE=/path/to/dashplay-bundle.tar \
  bash n1/dashplay/build-apks.sh ./out/n1-apks
(cd out/n1-apks && sha256sum ./*.apk > SHA256SUMS)
```

不指定 feed/bundle 时使用固定的上游版本、提交和 bundle 哈希。GitHub Actions 推送本分支的构建文件默认会打完整镜像；提交消息含 `[apks only]` 时只打升级包。工作流若已在默认分支注册，也可手动选择 `packages_only`。完整构建的产物包含镜像、校验报告、最终软件包清单和独立 APK。SDK 包未用设备信任的发行密钥签名，只将自己验证过的构建产物复制到设备；不要全局放宽签名策略。

把升级产物 APK 和对应 SHA256SUMS 放到 N1 的 `/tmp/n1-update/`，从**有线 SSH**执行。以下每条 apk 命令是独立选项：只运行你改过的包那一条。先停止车载模式可避免打断投屏，升级后按需打开。

```sh
cd /tmp/n1-update
sha256sum -c SHA256SUMS
n1-car-mode off
apk add --allow-untrusted ./dashplay-20*.apk
apk add --allow-untrusted ./luci-app-dashplay-*.apk
apk add --allow-untrusted ./luci-i18n-dashplay-zh-cn-*.apk
n1-car-mode on
```

## 如何验收

CI 从最终 Btrfs 分区核对实际蓝牙模块/vermagic、Wi-Fi 脚本和固件，生成经验证的 APK provider、快启计划与原加载器回退，运行目标 Python/Java 和 DashPlay 自检。QEMU 用成品的 UCI 在临时配置中反复切换两种模式；用成品 fw4 生成规则，并在一次性副本中分别重装 Core、LuCI 和翻译，检查配置和模拟身份/配对数据仍在。离线 APK 检查不运行实机服务钩子。

实机用第二只 U 盘从断电启动：确认 eth0 管理始终可达、开关和重启均生效、热点关联、蓝牙配对、有线和无线上屏、拔线恢复。标准 HTTPS 需用自己的有效域名，在 iPad/车机打开无端口地址，实际提交 HTTP/2 显示尺寸请求、切换横屏尺寸、点击地图并核对来源限制。首页 HTTP 200 不等于投屏通过。EC20 保持后置，不新增 WAN。保留旧启动盘可随时回退。
