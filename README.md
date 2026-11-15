# JDC-RE-OS-03 — OpenWrt for JDCloud RE-CS-03 (IPQ5018 + QCN6122, eMMC)

Builds a firmware image for the JDCloud RE-CS-03 (AX3000, 后羿/哪吒) on top of
two upstream OpenWrt trees. Everything device-specific lives in a patch series
plus a *seed* `.config`; the trees themselves are never forked.

## Two pipelines

| workflow | upstream | device patch | seed | trigger |
|---|---|---|---|---|
| `.github/workflows/build.yaml` | `openwrt/openwrt@v25.12.5` (vanilla 25.12 stable) | `patches-stable/` | `re-cs-03.config` | push (paths below) + manual |
| `.github/workflows/Fanchmwrt.yaml` | `fanchmwrt/fanchmwrt@fanchmwrt-25.12.6` (official stable) | `patches-fanchmwrt/` | `re-cs-03-fanchmwrt.config` | manual (`workflow_dispatch`) only |

Both end in a GitHub release: tag `stable-YYYY-MM-DD` for build.yaml,
`fanchmwrt-25.12.6-YYYY-MM-DD-HH-MM-SS` for Fanchmwrt.yaml. Beyond the newest
five, each workflow keeps one build per week and deletes the rest — build.yaml
keeps days 02/09/16/24, Fanchmwrt keeps 01/08/15/23.

```sh
gh workflow run build.yaml --ref main
gh workflow run Fanchmwrt.yaml --ref main
```

A run is ~3 h (cold ~3.5 h) and the release is only published when the build
job succeeds. build.yaml cancels an in-flight run when a new push lands.

## Layout

```
.github/workflows/       build.yaml (vanilla 25.12), Fanchmwrt.yaml (official stable)
patches-stable/          device patch series for openwrt/openwrt v25.12.5   <-- active
patches-fanchmwrt/       device patch series for fanchmwrt-25.12.6          <-- active
re-cs-03.config          seed for the vanilla 25.12 line
re-cs-03-fanchmwrt.config seed for the FanchmWrt line
files/                   overlay copied into the image (rc.local, shadow, sshd
                         hardening, uci-defaults/999-QOL_config: IPv6 + QoL wifi)
reference/oem/           OEM board.dtb + its text dump + uboot.mbn, the hardware
                         ground truth (read-only evidence, not used by CI)
tools/                   local checks that mirror CI (see tools/README.md)
WORKLOG.md               dated engineering log, newest decision last
LICENSES/                OpenWrt license texts carried over with the device patch
```

Both series carry the same device payload (11 files): DTS (`ipq5018-re-cs-03.dts`,
ESS model, installed through the `DEVICE_DTS_DIR=$(DTS_DIR)/qcom` overlay), the
two `ipq-wifi` board blobs (`board-jdcloud_re-cs-03.{ipq5018,qcn6122}`, sha256
`72dc2f28…`/`8f1a10c9…`), `ipq50xx.mk` device block, `board.d/02_network`,
`11-ath11k-caldata` (mmC cal), `05-wifi-migrate`, eMMC `platform.sh`,
`uboot-envtools` (`0:APPSBLENV`), the `ipq-wifi` Makefile `Build/Prepare` that
copies the blobs, plus two build fixes (`tools/gnulib` obstack, `rtl8812au-ct`
gcc-14).

`patches-stable/` is the 14-file superset: it also pins
`timezone='CST-8'`/`Asia/Shanghai` in `base-files/files/bin/config_generate` and
`net.netfilter.nf_conntrack_max=165535` in `etc/sysctl.conf`, because vanilla
OpenWrt defaults to UTC. `patches-fanchmwrt/` needs neither — that tree already
ships `hostname='FanchmWrt'`, `HKT-8`/`Asia/Hong Kong`.

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
- **`luci-theme-argon` only** in the FanchmWrt line: since 3.0.0 the theme ships
  the `argon-config` files itself, so cloning `luci-app-argon-config` on top
  collides at `package/install`.
- **Cache `restore-keys` must stay branch-scoped**; a bare `openwrt-build` key
  pulls another tree's `build_dir` with valid `.prepared` stamps.
- **No `qcom,dac-preset-short-cable`** on `&ge_phy` (see `reference/oem/README.md`).
- Every `CONFIG_PACKAGE_*=y`/`=n` line in a seed is re-asserted after
  `make defconfig`, because kconfig drops unknown symbols silently.

## Local checks (see `tools/README.md`)

```sh
python tools/check_workflows.py                             # repo invariants, offline
python tools/verify_device_patch.py                         # patch applies, DTS/shell/blobs ok
python tools/check_workflows.py --tree temp/patchcheck/tree # + seed symbols exist upstream
python tools/ssh_run.py @tools/router_probe.sh 60           # device readiness, read-only
python tools/test_sysupgrade.py --yes <image>               # sysupgrade -T, never flashes
```

`temp/` is gitignored scratch space (the clones the tools make, ~300 MB each)
and is never needed at runtime — delete it whenever.
