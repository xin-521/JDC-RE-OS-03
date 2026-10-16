#!/usr/bin/env python3
"""Port the JDCloud RE-CS-03 device support onto the NSS tree.

patches/re-cs-03.patch is generated against OpenWrt v25.12.5; the tree this job checks
out (qosmio/openwrt-ipq, branch 25.12-nss) is upstream openwrt-25.12 plus the NSS patch
set, so its device-support files can drift and their hunks can be rejected by `git apply`:

    package/boot/uboot-tools/uboot-envtools/files/qualcommax_ipq50xx
    package/firmware/ipq-wifi/Makefile
    target/linux/qualcommax/ipq50xx/base-files/etc/board.d/02_network
    target/linux/qualcommax/ipq50xx/base-files/etc/hotplug.d/firmware/11-ath11k-caldata
    target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh

This is the fallback path. Every edit is idempotent (marker check) and every anchor is a
candidate list, so a drifting neighbour only downgrades the hit to the next anchor. A miss
is reported but not fatal: the workflow's verify step re-checks the concrete result and is
what fails the job.
"""

import io

def read(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read()

def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

def _lines(path):
    return read(path).split("\n")

def _find(lines, anchors, nth=1, start=0):
    """anchors: anchor line or list of candidates. Returns (index, anchor) or (None, None)."""
    if isinstance(anchors, str):
        anchors = [anchors]
    for a in anchors:
        hits = [i for i, l in enumerate(lines) if i >= start and l.rstrip("\r") == a]
        if len(hits) >= nth:
            return hits[nth - 1], a
    return None, None

def _find_prefix(lines, prefix, start=0):
    """First line that starts with prefix. Returns (index, line) or (None, None)."""
    for i, l in enumerate(lines):
        if i >= start and l.rstrip("\r").startswith(prefix):
            return i, l
    return None, None

def insert(path, marker, anchors, block, nth=1, before=False):
    lines = _lines(path)
    if marker in "\n".join(lines):
        print("  = already ported: %s (%r)" % (path, marker))
        return
    i, a = _find(lines, anchors, nth)
    if i is None:
        print("  ! %s: no anchor among %r" % (path, anchors))
        return
    add = block.split("\n")
    lines[i:i] = add if before else []
    if not before:
        lines[i + 1:i + 1] = add
    write(path, "\n".join(lines))
    print("  + %s: %d line(s) %s %r" % (path, len(add), "before" if before else "after", a.strip()[:48]))

def append(path, marker, block):
    text = read(path)
    if marker in text:
        print("  = already ported: %s (%r)" % (path, marker))
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + block)
    print("  + %s: appended %d line(s)" % (path, block.count("\n")))

UBOOT = "package/boot/uboot-tools/uboot-envtools/files/qualcommax_ipq50xx"
WIFI = "package/firmware/ipq-wifi/Makefile"
NET = "target/linux/qualcommax/ipq50xx/base-files/etc/board.d/02_network"
CAL = "target/linux/qualcommax/ipq50xx/base-files/etc/hotplug.d/firmware/11-ath11k-caldata"
PLAT = "target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh"

print("porting jdcloud_re-cs-03 support onto the NSS tree")

# 1. uboot-envtools: eMMC APPSBLENV lives in a GPT partition on this board.
insert(UBOOT, "jdcloud,re-cs-03)",
       'case "$board" in',
       'jdcloud,re-cs-03)\n'
       '\tubootenv_add_mmc "0:APPSBLENV" "" "0x0" "0x40000" "0x10000"\n'
       '\t;;')

# 2. ipq-wifi: package the two local board-2.bin files (soc + qcn6122).
insert(WIFI, "define Build/Prepare",
       ["# Use ath10k-bdencoder from https://github.com/qca/qca-swiss-army-knife.git",
        "define Build/Compile"],
       'define Build/Prepare\n'
       '\t$(call Build/Prepare/Default)\n'
       '\t$(CP) ./files/board-* $(PKG_BUILD_DIR)/\n'
       'endef\n',
       before=True)
insert(WIFI, "jdcloud_re-cs-03 \\",
       ["\tiodata_wn-dax3000gr \\", "ALLWIFIBOARDS:= \\", "ALLWIFIBOARDS:="],
       "\tjdcloud_re-cs-03 \\")
# The $(eval $(call generate-ipq-wifi-package,...)) lines live at the bottom of the file,
# next to each other; anchor on any sibling, else on the first eval line of the block.
_lines_wifi = _lines(WIFI)
if "generate-ipq-wifi-package,jdcloud_re-cs-03" not in "\n".join(_lines_wifi):
    i, a = _find(_lines_wifi, [
        "$(eval $(call generate-ipq-wifi-package,jdcloud_re-ss-01,JDCloud RE-SS-01))",
        "$(eval $(call generate-ipq-wifi-package,jdcloud_re-cs-02,JDCloud RE-CS-02))",
    ])
    if i is None:
        i, a = _find_prefix(_lines_wifi, "$(eval $(call generate-ipq-wifi-package,")
    if i is None:
        print("  ! %s: no anchor for the generate-ipq-wifi-package eval" % WIFI)
    else:
        _lines_wifi[i + 1:i + 1] = ["$(eval $(call generate-ipq-wifi-package,jdcloud_re-cs-03,JDCloud RE-CS-03))"]
        write(WIFI, "\n".join(_lines_wifi))
        print("  + %s: eval for jdcloud_re-cs-03 after %r" % (WIFI, a.strip()[:48]))

# 3. 02_network: same lan1..lan3 / wan layout as the cmcc_mr3000d-ci group.
insert(NET, "jdcloud,re-cs-03",
       ["\tlinksys,mx2000|\\", "\tcmcc,mr3000d-ci|\\", "\tcmcc,pz-l8|\\"],
       "\tjdcloud,re-cs-03|\\",
       before=True)

# 4. ath11k caldata: eMMC ART, once for the SoC radio and once for the QCN6122 radio.
insert(CAL, "jdcloud,re-cs-03)",
       '\tcase "$board" in',
       '\tjdcloud,re-cs-03)\n'
       '\t\tcaldata_extract_mmc "0:ART" 0x1000 0x20000\n'
       '\t\tath11k_remove_regdomain\n'
       '\t\t;;',
       nth=1)
insert(CAL, 'caldata_extract_mmc "0:ART" 0x26800',
       ['\tcase "$board" in'],
       '\tjdcloud,re-cs-03)\n'
       '\t\tcaldata_extract_mmc "0:ART" 0x26800 0x20000\n'
       '\t\tath11k_remove_regdomain\n'
       '\t\t;;',
       nth=2)

# 5. platform.sh: sysupgrade support (eMMC A/B layout) + config carry-over.
lines = _lines(PLAT)
if "jdcloud,re-cs-03" not in "\n".join(lines):
    up, _ = _find(lines, "platform_do_upgrade() {")
    if up is None:
        print("  ! %s: no platform_do_upgrade()" % PLAT)
    else:
        i, a = _find(lines, ['\tcase "$(board_name)" in'], start=up)
        if i is None:
            print("  ! %s: no board_name case inside platform_do_upgrade()" % PLAT)
        else:
            lines[i + 1:i + 1] = [
                "\tjdcloud,re-cs-03)",
                '\t\tCI_KERNPART="0:HLOS"',
                '\t\tCI_ROOTPART="rootfs"',
                '\t\tCI_DATAPART="rootfs_data"',
                '\t\temmc_do_upgrade "$1"',
                "\t\t;;",
            ]
            write(PLAT, "\n".join(lines))
            print("  + %s: upgrade case in platform_do_upgrade() after %r" % (PLAT, a.strip()[:48]))

append(PLAT, "platform_copy_config()", "\n"
       "platform_copy_config() {\n"
       '\tcase "$(board_name)" in\n'
       "\tjdcloud,re-cs-03)\n"
       "\t\temmc_copy_config\n"
       "\t\t;;\n"
       "\tesac\n"
       "}\n")

print("port done")
