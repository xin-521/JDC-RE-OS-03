#!/usr/bin/env python3
"""Lint this repo before pushing: workflows, seeds, and the invariants that
have already bitten us once each.

    python tools/check_workflows.py                  # offline, no upstream tree
    python tools/check_workflows.py --tree temp/patchcheck/tree   # + seed symbols

Checks
  [1] both workflows parse and every `run:` block is valid bash
  [2] each workflow pins the upstream/branch/patch-dir/seed documented in README
  [3] no make variable (PATCH_DIR, FILES_DIR, TOPDIR, ...) is exported as env --
      make imports the environment, and PATCH_DIR silently strips every package
      of its patches (symptom: tools/ninja "no such option: --no-rebuild")
  [4] cache restore-keys stay branch scoped (a bare key imports another tree's
      build_dir with valid .prepared stamps)
  [5] seed hygiene: no BOM, trailing newline (the workflow appends with `cat`),
      the wpad pair, no luci-app-argon-config, QoL needs a full wpad
  [6] no `qcom,dac-preset-short-cable` property in either patch series (it makes
      the WAN 1G link flap and downshift to 100M)
  [7] optional --tree: every CONFIG_PACKAGE_*=y/=n symbol of both seeds exists
"""
import argparse
import io
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECT = {
    'build.yaml': dict(
        repository='openwrt/openwrt', branch='v25.12.5',
        patch_dir='patches-stable/', config='re-cs-03.config',
        seed='re-cs-03.config', release_prefix='stable'),
    'Fanchmwrt.yaml': dict(
        repository='fanchmwrt/fanchmwrt', branch='fanchmwrt-25.12.6',
        patch_dir='patches-fanchmwrt/', config='re-cs-03-fanchmwrt.config',
        seed='re-cs-03-fanchmwrt.config', release_prefix='fanchmwrt-25.12.6'),
    'ImmortalWRT.yaml': dict(
        repository='immortalwrt/immortalwrt', branch='openwrt-25.12',
        patch_dir='patches-immortalwrt/', config='re-cs-03-immortalwrt.config',
        seed='re-cs-03-immortalwrt.config', release_prefix='immortalwrt-25.12'),
}
MAKE_VARS = ('PATCH_DIR', 'HOST_PATCH_DIR', 'FILES_DIR', 'HOST_FILES_DIR', 'TOPDIR',
             'BUILD_DIR', 'STAGING_DIR', 'PKG_BUILD_DIR', 'KERNEL_PATCHVER')
fails = []


def note(ok, msg):
    print(('  ok   ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)


def read(p):
    return io.open(p, encoding='utf-8', newline='').read()


def read_norm(p):
    # the working tree is checked out with core.autocrlf=true, so parse content
    # with LF regardless of what git put on disk
    return read(p).replace('\r\n', '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tree', help='a pristine clone of the upstream tree, enables [7]')
    ap.add_argument('--strict', action='store_true',
                    help='[7]: also fail on symbols that the (uninstalled) feeds would provide')
    a = ap.parse_args()
    os.chdir(ROOT)

    print('[1] YAML and every run block')
    docs = {}
    for wf, exp in EXPECT.items():
        path = os.path.join('.github', 'workflows', wf)
        raw = read(path)
        doc = yaml.safe_load(raw)
        docs[wf] = (doc, raw)
        note(True, '%s parses' % wf)
        n = 0
        for job, spec in doc['jobs'].items():
            for step in spec.get('steps', []):
                body = step.get('run')
                if not body:
                    continue
                n += 1
                r = subprocess.run(['bash', '--noprofile', '--norc', '-n'],
                                   input=body.encode(), capture_output=True)
                note(r.returncode == 0, 'bash -n %s/%s' % (job, step.get('name', '?')[:44]))
        print('     %s: %d run blocks' % (wf, n))

    print('[2] pinned upstream / branch / patch dir / seed')
    for wf, exp in EXPECT.items():
        doc, raw = docs[wf]
        env = doc.get('env') or {}
        note(env.get('REMOTE_REPOSITORY') == exp['repository'],
             '%s REMOTE_REPOSITORY=%s' % (wf, env.get('REMOTE_REPOSITORY')))
        note(env.get('REMOTE_BRANCH') == exp['branch'],
             '%s REMOTE_BRANCH=%s' % (wf, env.get('REMOTE_BRANCH')))
        note(env.get('DEVICE_PATCH_DIR') == exp['patch_dir'],
             '%s DEVICE_PATCH_DIR=%s' % (wf, env.get('DEVICE_PATCH_DIR')))
        note(env.get('CONFIG_FILE') == exp['config'],
             '%s CONFIG_FILE=%s' % (wf, env.get('CONFIG_FILE')))
        note(env.get('RELEASE_PREFIX') == exp['release_prefix'],
             '%s RELEASE_PREFIX=%s' % (wf, env.get('RELEASE_PREFIX')))
        note(os.path.isdir(exp['patch_dir']) and
             any(f.endswith('.patch') for f in os.listdir(exp['patch_dir'])),
             '%s patch dir %s holds a series' % (wf, exp['patch_dir']))
        stale = [n for n, l in enumerate(raw.split('\n'), 1)
                 if re.search(r'25\.12\.\d', l) and 'Super-Henry' not in l
                 and exp['branch'].split('-')[-1] not in l]
        note(not stale, '%s no stale version string (lines %s)' % (wf, stale))

    print('[3] no OpenWrt make variable exported into the job env')
    for wf in EXPECT:
        env = docs[wf][0].get('env') or {}
        bad = [v for v in MAKE_VARS if v in env]
        note(not bad, '%s env is free of %s' % (wf, bad or MAKE_VARS))

    print('[4] cache keys are branch scoped')
    for wf in EXPECT:
        steps = docs[wf][0]['jobs'].get('build', {}).get('steps', [])
        keys = [s.get('with', {}).get('restore-keys') for s in steps
                if str(s.get('uses', '')).startswith('actions/cache')]
        note(keys and all('openwrt-build-${{ env.REMOTE_BRANCH }}-' in (k or '') for k in keys),
             '%s restore-keys=%s' % (wf, keys))

    print('[5] seed hygiene')
    qol = read_norm('files/etc/uci-defaults/999-QOL_config')
    qol_needs_full_wpad = bool(re.search(r'bss_transition|wnm_sleep_mode|proxy_arp', qol))
    for wf, exp in EXPECT.items():
        seed = read(exp['seed'])
        note(not seed.startswith('\ufeff'), '%s: no BOM' % exp['seed'])
        note(seed.endswith('\n'), '%s: ends with LF (the `cat seed >> .config` trap)' % exp['seed'])
        sym = dict(re.findall(r'(?m)^CONFIG_PACKAGE_([A-Za-z0-9._+-]+)=([yn])$', seed))
        full = [k for k, v in sym.items() if v == 'y' and re.fullmatch(r'wpad(-openssl|-mbedtls|-wolfssl)?', k)]
        basic = [k for k, v in sym.items() if v == 'y' and k.startswith('wpad-basic')]
        note(not (full and basic), '%s: no wpad variant conflict' % exp['seed'])
        note(not qol_needs_full_wpad or (full and not basic),
             '%s: 999-QOL_config needs WNM/PROXYARP and a full wpad is selected' % exp['seed'])
        note('luci-app-argon-config' not in [k for k, v in sym.items() if v == 'y'],
             '%s: luci-app-argon-config not selected' % exp['seed'])

    print('[6] QoL wireless + LAN defaults are self-consistent')
    # hostapd validates the whole BSS and drops the interface on the first error:
    #   "OCV: PMF needs to be enabled whenever using OCV" -> add_iface failed
    qol_txt = read_norm('files/etc/uci-defaults/999-QOL_config')
    ocv = re.findall(r"(?m)^set wireless\.(default_radio\d+)\.ocv='1'$", qol_txt)
    pmf = set(re.findall(r"(?m)^set wireless\.(default_radio\d+)\.ieee80211w='[12]'$", qol_txt))
    note(all(b in pmf for b in ocv), 'ocv=1 implies ieee80211w=1|2 (ocv blocks: %s)' % (ocv or 'none'))
    # radio0 = IPQ5018 internal 2.4GHz, radio1 = QCN6122 5GHz (see the DTS comments)
    htmode = dict(re.findall(r"(?m)^set wireless\.(radio\d+)\.htmode='([^']+)'$", qol_txt))
    note(not re.match(r'(HE|VHT)(80|160)$', htmode.get('radio0', '')),
         'radio0 (2.4GHz) htmode=%s is not 80/160MHz' % (htmode.get('radio0') or 'unset'))
    note(not re.match(r'(HT|HE|VHT)20$', htmode.get('radio1', '')),
         'radio1 (5GHz) htmode=%s is wider than 20MHz' % (htmode.get('radio1') or 'unset'))
    # a device on lan1-3 must get a lease and reach 192.168.1.1 unattended
    for want in ("set network.lan.proto='static'", "set network.lan.ipaddr='192.168.1.1'",
                 "set network.lan.netmask='255.255.255.0'", "set dhcp.lan.dhcpv4='server'",
                 "set dhcp.lan.ignore='0'", "set dhcp.lan.start='100'",
                 "set firewall.@zone[0].input='ACCEPT'"):
        note(want in qol_txt, 'QoL has %s' % want)

    print('[7] no qcom,dac-preset-short-cable in either series')
    for d in ('patches-stable', 'patches-fanchmwrt', 'patches-immortalwrt'):
        for f in sorted(os.listdir(d)):
            if not f.endswith('.patch'):
                continue
            hits = [n for n, l in enumerate(read(os.path.join(d, f)).split('\n'), 1)
                    if re.match(r'^\+\s*qcom,dac-preset-short-cable\s*;', l)]
            note(not hits, '%s/%s has no enabled dac-preset (lines %s)' % (d, f, hits))

    if a.tree:
        print('[8] seed symbols exist in %s' % a.tree)
        known = set()
        for dp, dns, fns in os.walk(a.tree):
            dns[:] = [x for x in dns if x not in ('.git', 'build_dir', 'staging_dir', 'bin', 'dl', 'tmp')]
            for f in fns:
                if not f.endswith(('Makefile', '.mk')):
                    continue
                try:
                    txt = io.open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
                except OSError:
                    continue
                known.update(re.findall(r'define\s+Package/([A-Za-z0-9._+-]+)', txt))
                known.update('kmod-' + m for m in re.findall(r'call\s+KernelPackage,([A-Za-z0-9._+-]+)', txt))
        for wf, exp in EXPECT.items():
            seed = read_norm(exp['seed'])
            syms = sorted(set(re.findall(r'(?m)^CONFIG_PACKAGE_([A-Za-z0-9._+-]+)=[yn]$', seed)))
            unknown = [s for s in syms if s not in known
                       and not s.startswith(('ath11k-firmware-', 'ipq-wifi-'))]
            # a kmod that is not in package/kernel is always a typo: kmods never
            # come from the luci/packages feeds.  Everything else may simply be
            # feed-only (feeds are not installed in a bare clone).
            bad_kmods = [s for s in unknown if s.startswith('kmod-')]
            note(not bad_kmods, '%s: every kmod symbol exists in-tree (bad=%s)'
                 % (exp['seed'], bad_kmods or 'none'))
            feed_only = [s for s in unknown if not s.startswith('kmod-')]
            if feed_only and a.strict:
                note(False, '%s: %d symbols not in tree (feeds assumed): %s'
                     % (exp['seed'], len(feed_only), feed_only))
            elif feed_only:
                print('  ..   %s: %d/%d symbols are feed-provided (not checked here, use --strict to fail)'
                      % (exp['seed'], len(feed_only), len(syms)))
            else:
                note(True, '%s: %d seed symbols all in-tree' % (exp['seed'], len(syms)))
    else:
        print('[8] skipped (pass --tree <pristine clone> to check seed symbols)')

    if a.tree:
        print('[9] patched-tree details (uboot-envtools)')
        envf = os.path.join(a.tree, 'package/boot/uboot-tools/uboot-envtools/files')
        fwd = read_norm(os.path.join(envf, 'fw_defaults')) if os.path.exists(os.path.join(envf, 'fw_defaults')) else ''
        note('[ -f /etc/fw_env.config ]' in fwd,
             'fw_defaults only calls fw_printenv when /etc/fw_env.config exists')
        ipp = read_norm(os.path.join(envf, 'qualcommax_ipq50xx')) if os.path.exists(os.path.join(envf, 'qualcommax_ipq50xx')) else ''
        note('ubootenv_add_mmc "0:APPSBLENV" "" "0x0" "0x40000" "0x40000" "1"' in ipp,
             'APPSBLENV geometry is envsize == sectorsize * numsec')
        # QCN6122 cal: the jdcloud branch must sit inside the b00a040 FIRMWARE
        # case.  Inserting it next to xiaomi,ax6000 applies to the QCN9074
        # section instead, the hotplug exits 1, phy1 never appears and the 5GHz
        # AP cannot start (seen on the first immortalwrt series revision).
        calp = os.path.join(a.tree, 'target/linux/qualcommax/ipq50xx/base-files/etc/hotplug.d/firmware/11-ath11k-caldata')
        cal = read_norm(calp) if os.path.exists(calp) else ''
        seg = cal.split('cal-ahb-b00a040.wifi.bin')[1].split('cal-ahb-b00b040.wifi.bin')[0] if 'cal-ahb-b00a040.wifi.bin' in cal else ''
        note('jdcloud,re-cs-03' in seg,
             'QCN6122 cal handler has the jdcloud branch')

    print('[10] qca8337 CPU link fix is wired up')
    # Kernel 6.12.100+ backported upstream e0a77b1ed9, which sets
    # QCA8K_PORT_PAD_SGMII_FORCE_MODE on fixed-link CPU ports.  Upstream still
    # ships 0751, which force-enables SGMII auto-negotiation on the very same
    # PAD, and the combination leaves the qca8337 CPU link "up" with zero
    # frames: LAN dead, WAN fine.  The fanchmwrt series must strip the bit, and
    # both workflows must trip if 0751 ever disappears upstream.
    hits = [f for f in sorted(os.listdir('patches-fanchmwrt'))
            if f.endswith('.patch') and
            re.search(r'(?m)^\+?-.*QCA8K_PORT_PAD_SGMII_FORCE_MODE',
                      read_norm(os.path.join('patches-fanchmwrt', f)))]
    note(bool(hits),
         'patches-fanchmwrt strips QCA8K_PORT_PAD_SGMII_FORCE_MODE (%s)'
         % (', '.join(hits) or 'no series does'))
    # Every line must decide explicitly from upstream's state: immortalwrt has
    # already dropped 0751 (force-mode-only wiring), the other two still ship
    # it and therefore need the 0799 strip once the kernel passes 6.12.100.
    for wf in EXPECT:
        note('0751-net-dsa-qca8k-always-enable-SGMII-auto-negotiation.patch'
             in docs[wf][1],
             '%s verify inspects 0751 (SGMII AN workaround)' % wf)
        note('0799-net-dsa-qca8k-do-not-use-SGMII-PAD-force-mode-on-qca8337.patch'
             in docs[wf][1],
             '%s verify inspects 0799 (SGMII force-mode strip)' % wf)

    print()
    if fails:
        print('FAILED %d check(s)' % len(fails))
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
