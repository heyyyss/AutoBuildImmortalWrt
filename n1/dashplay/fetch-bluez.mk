# Use the ImageBuilder's own 25.12.1 repository, keys and host apk flags.
n1-bluez:
	mkdir -p $(TOPDIR)/bin/n1-bluez
	$(APK) fetch --arch $(ARCH_PACKAGES) --output $(TOPDIR)/bin/n1-bluez bluez-libs bluez-daemon bluez-utils bluez-utils-extra
