# OEM reference dumps (read-only evidence)

Neither file is used by CI. They are the hardware ground truth the device port
was verified against on 2026-10-14, kept because re-extracting them needs a live
OEM unit with root.

| file | what it is | how it was used |
|---|---|---|
| `board.dtb` | `/sys/firmware/fdt` dumped from the stock JDCloud RE-CS-03 (19-partition GPT board) | parsed with a hand-written FDT dumper; authority for the LED/button GPIOs, WAN `ge_phy`, LAN QCA8337 mdio1 phy0-2, QCN6122 board data offsets (`0x4c400000`/`0x4d100000`) and the **absence** of `qcom,dac-preset-short-cable` |
| `uboot.mbn` | OEM APPSBL image | `strings` showed the GPT/partition names (`0:HLOS`, `rootfs`, `rootfs_data`, `0:APPSBLENV`) and the `flash 0:GPT` paths the upgrade script relies on |

Consequences that are already baked into the port and must survive any cleanup:

- `platform.sh` uses `CI_KERNPART="0:HLOS"` / `CI_ROOTPART="rootfs"` — there is no
  `_1` OS slot on this box, only the bootloader partitions are A/B.
- `ubootenv_add_mmc "0:APPSBLENV"` — the env partition is `mmcblk0p10`, 256 KiB.
- the internal GE PHY must NOT get `qcom,dac-preset-short-cable`, or the WAN link
  flaps and downshifts to 100M (verified on hardware, see WORKLOG).

Derived, kept under `temp/` (gitignored): `temp/dtb/board.dts`, `temp/dtb/dump_dtb.py`.
