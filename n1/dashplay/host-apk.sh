#!/bin/bash
# The slim target apk intentionally lacks mkpkg/mkndx. Use the same full host tool
# that generated the rootfs repository. Only the transient package directory is mounted.
set -eu
stage=$(realpath "${1:?package stage}"); shift
docker run --rm -u root -v "$stage:/stage" -w /stage \
    --entrypoint /home/build/immortalwrt/staging_dir/host/bin/apk \
    immortalwrt/imagebuilder:armsr-armv8-openwrt-25.12.1 "$@"
