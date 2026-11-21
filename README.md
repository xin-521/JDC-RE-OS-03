# JDC-RE-OS-03 — OpenWrt for JDCloud RE-CS-03 (IPQ5018 + QCN6122, eMMC)

Builds a firmware image for the JDCloud RE-CS-03 (AX3000, 后羿/哪吒) on top of
three upstream OpenWrt trees. Everything device-specific lives in a patch series
plus a *seed* `.config`; the trees themselves are never forked.

## Three pipelines

| workflow | upstream | device patch | seed | trigger |
|---|---|---|---|---|
| `.github/workflows/build.yaml` | `openwrt/openwrt@v25.12.5` (vanilla 25.12 stable) | `patches-stable/` | `re-cs-03.config` | push (paths below) + manual |
| `.github/workflows/Fanchmwrt.yaml` | `fanchmwrt/fanchmwrt@fanchmwrt-25.12.6` (official stable) | `patches-fanchmwrt/` | `re-cs-03-fanchmwrt.config` | manual (`workflow_dispatch`) only |
| `.github/workflows/ImmortalWRT.yaml` | `immortalwrt/immortalwrt@v25.12.2` (stable release tag) | `patches-immortalwrt/` | `re-cs-03-immortalwrt.config` | push (paths below) + manual |

Each ends in a GitHub release: tag `stable-YYYY-MM-DD` for build.yaml,
`fanchmwrt-25.12.6-YYYY-MM-DD-HH-MM-SS` for Fanchmwrt.yaml, and
`immortalwrt-25.12-YYYY-MM-DD-HH-MM-SS` for ImmortalWRT.yaml. Beyond the newest
five, each workflow keeps one build per week and deletes the rest — build.yaml
keeps days 02/09/16/24, the other two keep 01/08/15/23.

```sh
gh workflow run build.yaml --ref main
gh workflow run Fanchmwrt.yaml --ref main
gh workflow run ImmortalWRT.yaml --ref main
```

A run is ~2-3 h (cold ~3.5 h) and the release is only published when the build
job succeeds. build.yaml and ImmortalWRT.yaml cancel an in-flight run when a new
push lands.

## Layout

```
.github/workflows/       build.yaml (vanilla 25.12), Fanchmwrt.yaml (official
                         stable), ImmortalWRT.yaml (ImmortalWrt stable)
patches-stable/          device patch series for openwrt/openwrt v25.12.5   <-- active
patches-fanchmwrt/       device patch series for fanchmwrt-25.12.6          <-- active
patches-immortalwrt/     device patch series for immortalwrt v25.12.2       <-- active
re-cs-03.config          seed for the vanilla 25.12 line
re-cs-03-fanchmwrt.config seed for the FanchmWrt line
re-cs-03-immortalwrt.config seed for the ImmortalWrt line
files/                   overlay copied into the image (rc.local, shadow, sshd
                         hardening, uci-defaults/999-QOL_config: IPv6 + QoL wifi)
reference/oem/           OEM board.dtb + its text dump + uboot.mbn, the hardware
                         ground truth (read-only evidence, not used by CI)
tools/                   local checks that mirror CI (see tools/README.md)
WORKLOG.md               dated engineering log, newest decision last
LICENSES/                OpenWrt license texts carried over with the device patch
```

All three series carry the same device payload (11 files): DTS
(`ipq5018-re-cs-03.dts`, ESS model, installed through the
`DEVICE_DTS_DIR=$(DTS_DIR)/qcom` overlay), the two `ipq-wifi` board blobs
(`board-jdcloud_re-cs-03.{ipq5018,qcn6122}`, sha256 `72dc2f28…`/`8f1a10c9…`),
`ipq50xx.mk` device block, `board.d/02_network`, `11-ath11k-caldata` (mmC cal),
`05-wifi-migrate`, eMMC `platform.sh`, `uboot-envtools` (`0:APPSBLENV`), the
`ipq-wifi` Makefile entry that copies the blobs, plus two build fixes
(`tools/gnulib` obstack, `rtl8812au-ct` gcc-14).

`patches-stable/` is a 15-file superset: it also pins
`timezone='CST-8'`/`Asia/Shanghai` in `base-files/files/bin/config_generate` and
`net.netfilter.nf_conntrack_max=165535` in `etc/sysctl.conf`, because vanilla
OpenWrt defaults to UTC. `patches-fanchmwrt/` needs neither — that tree already
ships `hostname='FanchmWrt'`, `HKT-8`/`Asia/Hong Kong` — but it adds
`0799-…force-mode-on-qca8337.patch`, because that kernel (6.12.112) has the
force-mode backport while the tree still ships `0751` (SGMII AN).
`patches-immortalwrt/` drops both special cases: ImmortalWrt's
`default-settings-chn` package already sets `CST-8`/`Asia/Shanghai`, and it
keeps `nf_conntrack_max`. It pins the **stable release tag `v25.12.2`**
(kernel 6.12.103: `0751` still present, force mode not backported yet), so it
needs no `0799` either. The moving `openwrt-25.12` branch head is the
`25.12-SNAPSHOT` line (kernel 6.12.116, `0751` already dropped) and is
deliberately **not** what this pipeline builds.

## Invariants the workflows assert (do not "simplify" them away)

- **Never export `PATCH_DIR`** (or `FILES_DIR`, `TOPDIR`, `BUILD_DIR`, …) as a
  workflow env var: `make` imports the environment, and `PATCH_DIR` is OpenWrt's
  own quilt variable, so every package loses its patches — the symptom is
  `configure.py: error: no such option: --no-rebuild` in `tools/ninja`.
  Hence `DEVICE_PATCH_DIR`.
- **Seeds must end with a LF**: the workflow appends with `cat seed >> .config`,
  and a missing newline glues the last symbol onto the first `echo`.
- **`wpad-openssl=y` + `wpad-basic-mbedtls=n`** are a pair: `999-QOL_config` sets
  802.11v/proxy_arp, which hostapd-basic is compiled without. All wpad variants
  `CONFLICTS` on each other.
- **`luci-theme-argon` only** in the FanchmWrt/ImmortalWrt lines: since 3.0.0 the
  theme ships the `argon-config` files itself, so adding `luci-app-argon-config`
  on top collides at `package/install`. ImmortalWrt gets the theme from its own
  luci feed; no git clone is needed (and `luci-compat`/`luci-lua-runtime` do not
  exist in that feed, so `luci-app-diskman` is not selected there either).
- **Cache `restore-keys` must stay branch-scoped**; a bare `openwrt-build` key
  pulls another tree's `build_dir` with valid `.prepared` stamps.
- **No `qcom,dac-preset-short-cable`** on `&ge_phy` (see `reference/oem/README.md`).
- **qca8337 CPU link has two valid upstream states** and each workflow must pick
  the matching one:
  - `0751` present + kernel < 6.12.111 → the force-mode backport does not exist
    yet, ship neither `0799` (ImmortalWRT.yaml at `v25.12.2`, kernel 6.12.103);
  - `0751` present + kernel ≥ 6.12.111 → the device series must carry the `0799`
    strip (Fanchmwrt.yaml today; build.yaml once its kernel passes 6.12.110);
  - `0751` absent + kernel ≥ 6.12.111 → upstream's force-mode-only wiring, do
    **not** add `0799`.
  Mixing the two (force mode + forced SGMII AN) leaves LAN "up" but carrying
  zero frames. The backport (`e0a77b1ed9`) first ships in stable **6.12.111**
  (checked against the .109/.110/.111/.112/.113/.116 drivers); the earlier
  6.12.100 cut-off was wrong and would have demanded `0799` on a 6.12.103 tag
  where the code it patches does not exist. `kernel-6.12` stores the version as
  `.103`/`.116`, so every workflow must prefix `6.12` before comparing — a bare
  `split(".")` yields an empty major and silently takes the "predates" path.
- **The `jdcloud,re-cs-03` cal branch must sit inside the QCN6122
  `cal-ahb-b00a040.wifi.bin` case** (after `yuncore,ax830`, before `esac`).
  Inserted before `xiaomi,ax6000` it lands in the QCN9074 case instead, the
  hotplug falls through to `*) exit 1`, no cal file is written and phy1 (5GHz)
  never registers — this happened in ImmortalWrt's first revision.
- Every `CONFIG_PACKAGE_*=y`/`=n` line in a seed is re-asserted after
  `make defconfig`, because kconfig drops unknown symbols silently.
- The ImmortalWrt image carries WireGuard: `kmod-wireguard` (netsupport.mk,
  pulls chacha20poly1305/curve25519 + udptunnel4/6), `wireguard-tools` (`wg`
  plus the netifd proto handler) and `luci-proto-wireguard`. The workflow
  checks all three in `.config` *and* in the produced `.manifest`, so a feed
  that drops one cannot ship a silently wireguard-less image.

## Local checks (see `tools/README.md`)

```sh
python tools/check_workflows.py                             # repo invariants, offline
python tools/verify_device_patch.py                         # patch applies, DTS/shell/blobs ok
python tools/verify_device_patch.py \
    --repo https://github.com/immortalwrt/immortalwrt --branch v25.12.2 \
    --patch patches-immortalwrt/re-cs-03-immortalwrt-25.12.patch \
    --workdir temp/patchcheck-immortalwrt                   # ImmortalWrt line
python tools/check_workflows.py --tree temp/patchcheck/tree # + seed symbols exist upstream
python tools/ssh_run.py @tools/router_probe.sh 60           # device readiness, read-only
python tools/test_sysupgrade.py --yes <image>               # sysupgrade -T, never flashes
```

`temp/` is gitignored scratch space (the clones the tools make, ~300 MB each)
and is never needed at runtime — delete it whenever.
