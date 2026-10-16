#!/usr/bin/env python3
"""Make the QSDK/NSS feed packages survive this tree's compiler flags.

Two independent problems, both fatal, both in the feed's own build flags:

1. scripts/Makefile.extrawarn enables -Wmissing-prototypes and
   -Wmissing-declarations for every kernel build (kernel and modules), and on
   this tree warnings are promoted to errors.  The QSDK code predates that, and
   the packages whose ipq50xx HAL the fork never built do not silence it in
   their own EXTRA_CFLAGS, so they die with

       hal/ipq50xx/nss_crypto_ce5.c:235:5: error: no previous prototype for
       'nss_crypto_ce5_ctx_fill' [-Werror=missing-prototypes]

2. gcc >= 14 turns -Wimplicit-function-declaration into an error by default,
   and qca-nss-crypto's 6.12-era HAL calls of_find_compatible_node() without
   including <linux/of.h>:

       hal/ipq50xx/nss_crypto_hw.c:39:13: error: implicit declaration of
       function 'of_find_compatible_node' [-Wimplicit-function-declaration]

   An implicit declaration also makes the compiler assume the function returns
   int, which truncates the pointer it actually returns on arm64, so the header
   is force-included instead of only muting the warning.

Add the two -Wno-missing-* flags and -Wno-implicit-function-declaration to any
nss_packages Makefile that passes EXTRA_CFLAGS without them, and force-include
<linux/of.h> for qca-nss-crypto.  kbuild maps EXTRA_CFLAGS onto ccflags-y,
which is appended after KBUILD_CFLAGS, so the later -Wno-* wins.

Idempotent: only the flags that are actually missing are inserted.
"""
import glob
import io
import os
import re
import sys

FLAGS = (
    "-Wno-missing-prototypes",
    "-Wno-missing-declarations",
    "-Wno-implicit-function-declaration",
)
OF_H = "-include linux/of.h"
CRYPTO = os.path.join("feeds", "nss_packages", "qca-nss-crypto", "Makefile")
FEEDS = "feeds/nss_packages"
ASSIGN = re.compile(r"^(EXTRA_CFLAGS\s*[:+]?=\s*)", re.M)


def add_flags(text, match, flags):
    """Insert only the flags that are missing, right after the EXTRA_CFLAGS=."""
    missing = [f for f in flags if f not in text]
    if not missing:
        return text, False
    return text[: match.end()] + " ".join(missing) + " " + text[match.end():], True


def patch(path, extra=()):
    text = io.open(path, encoding="utf-8", newline="").read()
    match = ASSIGN.search(text)
    if not match:
        return None
    text, changed = add_flags(text, match, FLAGS)
    text, changed2 = add_flags(text, ASSIGN.search(text), extra)
    changed = changed or changed2
    if changed:
        io.open(path, "w", encoding="utf-8", newline="").write(text)
    return changed


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

    if os.path.isfile(CRYPTO):
        if patch(CRYPTO, extra=(OF_H,)):
            patched.append(CRYPTO + " (+of.h)")

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
    if os.path.isfile(CRYPTO):
        text = io.open(CRYPTO, encoding="utf-8").read()
        for want in ("Wno-missing-prototypes", "Wno-implicit-function-declaration", OF_H):
            if want not in text:
                print("qca-nss-crypto/Makefile still lacks %s" % want, file=sys.stderr)
                return 1
        print("  ok qca-nss-crypto carries the flags and <linux/of.h>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
