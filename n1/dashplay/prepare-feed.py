"""Prepare a pinned OpenWrt feed, leaving the original checkout untouched."""
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
edit = runpy.run_path(str(here / 'patch-bundle.py'))['edit']
feed = Path(sys.argv[1])
(feed / 'dashplay/patch-bundle.py').write_bytes((here / 'patch-bundle.py').read_bytes())
edit(feed, 'dashplay/Makefile', 'PKG_RELEASE:=1', 'PKG_RELEASE:=' + sys.argv[2])
edit(feed, 'dashplay/Makefile', 'tar -xf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR)/bundle',
     'tar -xf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR)/bundle\n\tpython3 $(CURDIR)/patch-bundle.py $(PKG_BUILD_DIR)/bundle')
edit(feed, 'dashplay/Makefile', 'EXTRA_DEPENDS:=python3', 'EXTRA_DEPENDS:=n1-car-support (>=1), python3')
edit(feed, 'dashplay/files/dashplay.init', 'START=99', 'START=21')
edit(feed, 'dashplay/files/dashplay.init', 'config_load dashplay',
     'if [ "$(uci -q get dashplay.main.enabled)" != 1 ]; then /usr/sbin/n1-car-mode apply || return 1; fi\n\tconfig_load dashplay')
edit(feed, 'dashplay/files/dashplay.init', 'procd_open_instance\n',
     'procd_open_instance\n\tprocd_set_param env PATH=/usr/libexec/carplay-compat:/usr/sbin:/usr/bin:/sbin:/bin\n')
# procd supervises this async wait, so a slow radio cannot block the boot sequence.
edit(feed, 'dashplay/files/dashplay.init', 'command /usr/bin/python3 /opt/dashplay/supervisor_openwrt.py --root /opt/dashplay',
     'command /usr/libexec/n1-dashplay-start')
for option, old, new in [('wifi','auto','n1_car'), ('viewer_port','','443'), ('update_check','1','0'), ('tesla_mode','0','1')]:
    edit(feed, 'dashplay/files/dashplay.config', f"option {option} '{old}'", f"option {option} '{new}'")
# Upstream updater installs the upstream channel, which cannot preserve the N1 port/init patches.
(feed / 'dashplay/files/dashplay-update').write_text("#!/bin/sh\necho 'N1 firmware: update the matching Core/LuCI APK from the N1 build.' >&2\nexit 1\n")
ui = 'luci-app-dashplay/htdocs/luci-static/resources/view/dashplay.js'
edit(feed, ui, "'enabled', _('Enable')", "'enabled', _('车载模式（关闭后使用旁路由）')")
edit(feed, ui, 'It must differ from the settings page port, 80, 443 and 7000.',
     '443 is available for standard HTTPS on the N1. The settings port, 80 and 7000 are reserved.')
# The vehicle network must never be switched to the household LAN by auto-selection.
edit(feed, ui, "o.value('auto', _('Automatic (first access point, 5 GHz first)'));", "o.value('n1_car', 'DashPlay-N1');")
start = (feed / ui).read_text()
a = start.index("\t\tuci.sections('wireless'")
end = start.index("o.value('external',", a)
(feed / ui).write_text(start[:a] + start[start.index('\n', end):])
edit(feed, 'luci-app-dashplay/Makefile', 'include $(TOPDIR)/feeds/luci/luci.mk',
     'PKG_VERSION:=0.261102.35991\nPKG_RELEASE:=' + sys.argv[2] + '\nPKG_PO_VERSION:=0.261102.35991-r' + sys.argv[2] + '\ninclude $(TOPDIR)/feeds/luci/luci.mk')
