# Pinned kernel DTS include (read-only evidence)

`ipq5018.dtsi` is the **upstream Linux 6.12** file, fetched verbatim:

```sh
curl -o reference/kernel/ipq5018.dtsi \
  https://raw.githubusercontent.com/torvalds/linux/v6.12/arch/arm64/boot/dts/qcom/ipq5018.dtsi
```

Why it lives here: the port DTS references labels that the kernel base tree
defines but that the OpenWrt tree only re-patches (`xo_board_clk`,
`blsp1_uart1`, …). Without a kernel checkout, `tools/verify_device_patch.py`
cannot tell a typo'd `&label` from a kernel-provided one, so it resolves the
port DTS against the tree's own `patches-6.12/` **plus** this file. Both our
pipelines run kernel 6.12, one copy covers both.

Re-fetch it (and update this note) when a line moves to a newer kernel.
