#!/usr/bin/env python3
"""Make the QSDK/NSS feed packages survive the kernel >= 6.11 warning flags.

scripts/Makefile.extrawarn enables -Wmissing-prototypes and
-Wmissing-declarations for every kernel build (both kernel and modules), and on
this tree warnings are promoted to errors.  The QSDK code predates that: the
packages that do build on 6.12 already silence it in their own EXTRA_CFLAGS
(qca-ssdk: -Wno-missing-prototypes -Wno-missing-declarations; qca-nss-drv: the
same plus -Wno-empty-body), but the packages whose ipq50xx HAL the fork never
built do not, and die with

    hal/ipq50xx/nss_crypto_ce5.c:235:5: error: no previous prototype for
    'nss_crypto_ce5_ctx_fill' [-Werror=missing-prototypes]

Add the same two flags to any nss_packages Makefile that passes EXTRA_CFLAGS
without them.  kbuild maps EXTRA_CFLAGS onto ccflags-y, which is appended after
KBUILD_CFLAGS, so the later -Wno-* wins over the kernel's -Wmissing-*.

Idempotent: files that already carry the flag are left untouched.
"""
import glob
import io
import os
import re
import sys

FLAGS = "-Wno-missing-prototypes -Wno-missing-declarations "
FEEDS = "feeds/nss_packages"
ASSIGN = re.compile(r"^(EXTRA_CFLAGS\s*[:+]?=\s*)", re.M)


def patch(path):
    text = io.open(path, encoding="utf-8", newline="").read()
    if "Wno-missing-prototypes" in text:
        return False
    match = ASSIGN.search(text)
    if not match:
        return None
    io.open(path, "w", encoding="utf-8", newline="").write(
        text[: match.end()] + FLAGS + text[match.end():]
    )
    return True


def main():
    if not os.path.isdir(FEEDS):
        print("no %s (feed not updated yet?)" % FEEDS, file=sys.stderr)
        return 1

    patched, already, bare = [], [], []
    for path in sorted(glob.glob(os.path.join(FEEDS, "*", "Makefile"))):
        result = patch(path)
        if result is True:
            patched.append(path)
        elif result is False:
            already.append(path)
        else:
            bare.append(path)

    for path in patched:
        print("  patched          %s" % path)
    for path in already:
        print("  already ok       %s" % path)
    for path in bare:
        print("  no EXTRA_CFLAGS  %s" % path)
    print(
        "%d patched, %d already ok, %d without EXTRA_CFLAGS"
        % (len(patched), len(already), len(bare))
    )

    # the package that broke the last run must be fixed now
    crypto = os.path.join(FEEDS, "qca-nss-crypto", "Makefile")
    if os.path.isfile(crypto):
        text = io.open(crypto, encoding="utf-8").read()
        if "Wno-missing-prototypes" not in text:
            print(
                "qca-nss-crypto/Makefile still lacks the flag",
                file=sys.stderr,
            )
            return 1
        print("  ok qca-nss-crypto carries -Wno-missing-prototypes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
