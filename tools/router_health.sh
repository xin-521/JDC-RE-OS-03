#!/bin/sh
# Read-only health check for the JDCloud RE-CS-03 running OpenWrt.
#
#   python tools/ssh_run.py @tools/router_health.sh
#
# It only reads: /proc, /sys, dmesg, logread, uci get, ethtool, iwinfo, iw.
# No uci set/commit, no service restart, no mount, no write to the device.
#
# What to look at, in order:
#   2  LAN/DSA data path - the qca8337 CPU link is the fragile part. A link
#      that reports "up" while every rx counter stays 0 is the failure mode we
#      hit on 25.12.6 (SGMII PAD force mode); see WORKLOG 2026-11-15.
#   3  5 GHz - with country=DE + HE160 the ACS often lands on a DFS channel and
#      hostapd then needs a 60 s..600 s CAC, during which the AP is invisible
#      (NO-CARRIER, Tx-Power 0 dBm). Compare the DFS-CAC-* lines with uptime.
#   4  dmesg - known noise is listed in section 6; anything with a call trace,
#      BUG: or OOM is not noise.
#   6  The same err/warn lines with their counts, so a *new* line stands out.

echo "== 1 identity =="
cat /etc/openwrt_release 2>/dev/null | grep -E 'RELEASE|REVISION'
uname -r
ubus call system board 2>/dev/null | sed -n 's/.*"model": "\(.*\)".*/model=\1/p'
uptime

echo
echo "== 2 LAN / DSA data path =="
for i in lan1 lan2 lan3; do
	state=$(cat /sys/class/net/$i/operstate 2>/dev/null)
	speed=$(ethtool $i 2>/dev/null | sed -n 's/.*Speed: \(.*\)/\1/p')
	echo "$i: state=$state speed=${speed:-?}"
done
echo "-- per-port switch MIB (rx must grow with a live cable) --"
for i in lan1 lan2 lan3; do
	echo "$i: $(ethtool -S $i 2>/dev/null | grep -E 'rx_packets|tx_packets' | tr -s ' ' | tr '\n' ' ')"
done
echo "-- conduit + WAN counters --"
ip -s link show eth0 2>/dev/null | sed -n '1,4p'
ip -s link show wan 2>/dev/null | sed -n '1,4p'
echo "-- neighbours and leases --"
ip neigh 2>/dev/null | grep -v FAILED | head -6
cat /tmp/dhcp.leases 2>/dev/null | head -6

echo
echo "== 3 wireless =="
for i in phy0-ap0 phy1-ap0; do
	iwinfo $i info 2>/dev/null | grep -E 'ESSID|Channel:|Tx-Power'
	echo "$i stations: $(iw dev $i station dump 2>/dev/null | grep -c '^Station')"
done
iw reg get 2>/dev/null | sed -n '2p'
echo "-- ACS / DFS / CAC history (compare with uptime) --"
logread 2>/dev/null | grep -iE 'ACS-COMPLETED|DFS-CAC|AP-ENABLED|radar' | tail -6

echo
echo "== 4 dmesg err/warn =="
dmesg 2>/dev/null | grep -iE 'error|fail|warn|timeout|denied|segfault|call trace|BUG:|oom|killed process' | sed 's/^\[ *\([0-9.]*\)\] */\1 /' | head -40
echo "count: $(dmesg 2>/dev/null | grep -icE 'error|fail|warn|timeout|denied|segfault|call trace|BUG:|oom|killed process')"

echo
echo "== 5 logread err/warn =="
logread 2>/dev/null | grep -iE 'error|fail|denied|crash|not supported|unsupported' | tail -20

echo
echo "== 6 the same lines with counts (a new line stands out here) =="
dmesg 2>/dev/null | grep -iE 'error|fail|warn|timeout|denied' | sed 's/^\[ *[0-9.]*\] //' | sed 's/[0-9]\{2,\}/N/g' | sort | uniq -c | sort -rn | head -15

echo
echo "== 7 storage / overlay / fw_env =="
df -h / /tmp /overlay 2>/dev/null
cat /etc/fw_env.config 2>/dev/null
fw_printenv 2>&1 | head -12

echo
echo "== 8 thermal / memory / conntrack / taint =="
for z in /sys/class/thermal/thermal_zone*; do [ -r "$z/temp" ] && echo "$(cat $z/type 2>/dev/null): $(( $(cat $z/temp) / 1000 ))C"; done
grep -E 'MemTotal|MemAvailable|SReclaimable' /proc/meminfo
echo "conntrack=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null)/$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null)"
echo "taint=$(cat /proc/sys/kernel/tainted) (4096 = out-of-tree module: qca_ssdk/qca_nss_dp/fwx, expected here)"
grep -E 'qca_ssdk|qca_nss_dp|fwx' /proc/modules | cut -d' ' -f1 | tr '\n' ' '
echo

echo
echo "== 9 services / crash check =="
echo "addr: $(ip -4 addr show | grep -E 'inet ' | grep -v '127.0.0.1' | tr -s ' ' | cut -d' ' -f3- | tr '\n' ' ')"
echo "procs=$(ls /proc | grep -c '^[0-9]')"
echo "call trace / BUG / OOM: $(dmesg 2>/dev/null | grep -icE 'call trace|BUG:|out of memory|killed process')"
echo "== done =="
