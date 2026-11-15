#!/bin/sh
# Read-only upgrade-path probe for the JDCloud RE-CS-03.
#
#   python tools/ssh_run.py @tools/router_probe.sh 60
#
# Answers "can this box take a sysupgrade image, and does it keep its config?"
# without writing anything: partitions, find_mmc_part, platform.sh's device
# branch, the fstools config-backup extractor, and the tools sysupgrade needs.

echo "== board =="
. /lib/functions.sh
board_name
. /etc/openwrt_release && echo "$DISTRIB_DESCRIPTION"

echo
echo "== mmc partitions (PARTNAME -> node, size) =="
for d in /sys/block/mmcblk*/mmcblk*p*; do
	n=$(grep PARTNAME "$d/uevent" 2>/dev/null | cut -f2 -d=)
	[ -n "$n" ] || continue
	echo "$n -> /dev/$(basename "$d") $(($(cat "$d/size") * 512))B"
done

echo
echo "== find_mmc_part (what platform.sh resolves) =="
for p in "0:HLOS" rootfs rootfs_data rootfs_1; do
	echo "$p -> $(find_mmc_part "$p")"
done

echo
echo "== platform.sh device branch =="
sed -n '/jdcloud,re-cs-03)/,+5p' /lib/upgrade/platform.sh
sed -n '/^platform_copy_config/,/^}/p' /lib/upgrade/platform.sh

echo
echo "== upgrade tooling =="
ls -l /sbin/sysupgrade /lib/upgrade/emmc.sh /lib/upgrade/platform.sh /usr/bin/fwtool 2>&1

echo
echo "== config preservation =="
echo "-- /lib/upgrade/keep.d --"
ls /lib/upgrade/keep.d/ 2>/dev/null
echo "-- /etc/sysupgrade.conf --"
cat /etc/sysupgrade.conf 2>/dev/null
echo "-- fstools can pull a config backup off the data partition --"
strings /lib/libfstools.so 2>/dev/null | grep -i 'sysupgrade' | head -3

echo
echo "== /tmp headroom (the image is ~22MB and is copied there for the test) =="
df -h /tmp / | tail -3
