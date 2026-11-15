# tools/ — local checks that mirror what CI enforces

All of these are offline unless they clone an upstream tree; none of them touch
a flash partition.

| script | what it does |
|---|---|
| `verify_device_patch.py` | clones the pinned upstream tree (shallow, into `temp/patchcheck/`), applies a device patch series, and asserts: `git apply` clean, all touched files present, `sh -n` on the injected shell scripts, the two `ipq-wifi` board-blob sha256 values, and that every `&label` in the port DTS resolves inside that tree. `--prev-branch` also prints upstream drift on the touched files — run it before bumping a branch. |
| `check_workflows.py` | parses both workflows, `bash -n`s every `run:` block, checks the pinned repo/branch/patch-dir/seed/release prefix, that no OpenWrt make variable is exported as env, that cache keys stay branch scoped, seed hygiene (BOM/LF/trailing newline, wpad pair, no `luci-app-argon-config`), that neither series re-enables `qcom,dac-preset-short-cable`, and — with `--tree` — that every seed symbol exists upstream. |
| `router_probe.sh` | read-only device probe: partitions, `find_mmc_part`, `platform.sh`'s device branch, `emmc.sh`, the fstools config-backup extractor, `/etc/sysupgrade.conf`, `/tmp` headroom. Run it through `ssh_run.py`. |
| `ssh_run.py` | `ssh_run.py '<cmd>'` or `ssh_run.py @script` on the router; credentials from `ROUTER_HOST`/`ROUTER_USER`/`ROUTER_PASS`. |
| `test_sysupgrade.py` | uploads an image to `/tmp` and runs `sysupgrade -T` (validation only, never flashes), then deletes it. Needs `--yes`; refuses anything outside `/tmp`; checks free space and sha256 first. |

Typical sequence before flashing a new build:

```sh
python tools/check_workflows.py                       # repo invariants
python tools/verify_device_patch.py                   # patch still applies + DTS/shell/blobs ok
python tools/check_workflows.py --tree temp/patchcheck/tree   # seed symbols exist
python tools/ssh_run.py @tools/router_probe.sh 60     # device readiness (read-only)
python tools/test_sysupgrade.py --yes <release>/…-squashfs-sysupgrade.bin
```

The image to flash is always `…-squashfs-sysupgrade.bin`; `factory.bin` is the
first-install path (OEM firmware / U-Boot), and the sysupgrade artifact is a tar,
not a FIT — do not `dd` it. `0:HLOS` is exactly 6 MiB while the FIT kernel is
about 5.25 MiB, so the kernel has ~780 KiB of headroom; `emmc_do_upgrade` does
not clamp.
