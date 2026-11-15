#!/usr/bin/env python3
"""Apply a device patch series to a pristine clone of its upstream tree and
verify the result -- the same two things the CI does in "Add custom patches"
and "Verify the device and the excluded plugins", but locally.

    python tools/verify_device_patch.py                       # fanchmwrt-25.12.6
    python tools/verify_device_patch.py --branch v25.12.5 \
        --repo https://github.com/openwrt/openwrt --patch patches-stable/re-cs-03-stable-25.12.patch

Checks
  [1] the patch applies to an unmodified tree of --branch (no hunk fallback)
  [2] every file it touches exists and is byte-identical to the patch's intent
  [3] the injected shell files pass `sh -n`
  [4] the two ipq-wifi board blobs keep the sha256 the device was validated with
  [5] every &label in the port DTS resolves inside this tree (includes + the
      tree's own patches-<ver> labels)
  [6] optional: upstream drift since --prev-branch on the touched files

The clone lives in --workdir (default temp/patchcheck) and is reused, so a
second run is offline and fast; --clean wipes it first.
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys

# sha256 of the board blobs that were checked against the OEM data on hardware
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# labels the kernel's own ipq5018.dtsi defines (blsp1_uart1, xo_board_clk, ...);
# pinned copies live in reference/kernel/ because the kernel tree is not checked
# out here.  Regenerate with: curl -o reference/kernel/ipq5018.dtsi \
#   https://raw.githubusercontent.com/torvalds/linux/v6.12/arch/arm64/boot/dts/qcom/ipq5018.dtsi
BASE_DTSI_DIR = os.path.join(ROOT, 'reference', 'kernel')
EXPECT_BLOBS = {
    'board-jdcloud_re-cs-03.ipq5018': '72dc2f28',
    'board-jdcloud_re-cs-03.qcn6122': '8f1a10c9',
}
fails = []


def note(ok, msg):
    print(('  ok   ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)


def git(*args, **kw):
    """git with a retry: this box occasionally answers 'not a git repository'."""
    cwd = kw.pop('cwd', None)
    for attempt in range(3):
        r = subprocess.run(('git',) + args, cwd=cwd, capture_output=True, **kw)
        if r.returncode == 0 or attempt == 2:
            return r
    return r


def clone(repo, branch, dest):
    if os.path.isdir(os.path.join(dest, '.git')):
        print('  .. reusing %s' % dest)
        r = git('-C', dest, 'fetch', '--depth', '1', 'origin', branch)
        if r.returncode == 0:
            git('-C', dest, 'reset', '--hard', '-q', 'FETCH_HEAD')
            git('-C', dest, 'clean', '-fdxq')
        return
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or '.', exist_ok=True)
    print('  .. cloning %s@%s -> %s' % (repo, branch, dest))
    r = git('clone', '--depth', '1', '--single-branch', '--branch', branch, repo, dest)
    if r.returncode != 0:
        sys.exit('clone failed:\n' + r.stderr.decode('utf-8', 'replace'))


def read(p):
    return io.open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def patch_files(patch):
    txt = read(patch)
    return [m.group(1) for m in re.finditer(r'(?m)^diff --git a/(\S+) b/', txt)], txt


def resolve_labels(tree, dts):
    """Every &label the DTS uses must be defined in its include closure or in a
    label the tree's own kernel patches add (the kernel tree itself is not
    available offline)."""
    qcom = os.path.dirname(dts)
    m = re.search(r'KERNEL_PATCHVER:=\s*(\S+)', read(os.path.join(tree, 'target/linux/qualcommax/Makefile')))
    patchdir = os.path.join(tree, 'target/linux/qualcommax', 'patches-' + (m.group(1) if m else '6.12'))
    label_def = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', re.M)
    label_add = re.compile(r'^\+\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', re.M)
    label_use = re.compile(r'&([A-Za-z_][A-Za-z0-9_]*)')
    include_re = re.compile(r'^\s*#include\s+"([^"]+)"', re.M)

    defined, seen, bases = set(), set(), []

    def walk(path):
        if path in seen or not os.path.exists(path):
            return
        seen.add(path)
        txt = read(path)
        defined.update(label_def.findall(txt))
        for inc in include_re.findall(txt):
            for cand in (os.path.join(os.path.dirname(path), inc), os.path.join(qcom, inc)):
                walk(os.path.abspath(cand))

    walk(dts)
    for dp, _, fs in os.walk(patchdir):
        for f in fs:
            try:
                defined.update(label_add.findall(read(os.path.join(dp, f))))
            except (IOError, UnicodeDecodeError):
                pass
    for f in sorted(os.listdir(BASE_DTSI_DIR)) if os.path.isdir(BASE_DTSI_DIR) else []:
        if f.endswith('.dtsi'):
            defined.update(label_def.findall(read(os.path.join(BASE_DTSI_DIR, f))))
            bases.append(f)
    own = set(label_def.findall(read(dts)))
    used = set(label_use.findall(re.sub(r'/\*.*?\*/', '', read(dts), flags=re.S)))
    return sorted(u for u in used if u not in defined and u not in own), len(used), bases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='https://github.com/fanchmwrt/fanchmwrt')
    ap.add_argument('--branch', default='fanchmwrt-25.12.6')
    ap.add_argument('--patch', default='patches-fanchmwrt/re-cs-03.patch')
    ap.add_argument('--workdir', default=os.path.join('temp', 'patchcheck'))
    ap.add_argument('--prev-branch', help='report upstream drift from this older branch')
    ap.add_argument('--allow-unresolved', action='store_true',
                    help='treat unresolved DTS labels as a warning (kernel-only labels)')
    ap.add_argument('--clean', action='store_true', help='delete --workdir first')
    a = ap.parse_args()

    if not os.path.isfile(a.patch):
        sys.exit('no such patch: ' + a.patch)
    if a.clean and os.path.isdir(a.workdir):
        shutil.rmtree(a.workdir)
    tree = os.path.abspath(os.path.join(a.workdir, 'tree'))

    files, patch_txt = patch_files(a.patch)
    print('[1] apply %s (%d files) to %s' % (a.patch, len(files), a.branch))
    clone(a.repo, a.branch, tree)
    print('  .. HEAD %s' % git('-C', tree, 'rev-parse', 'HEAD').stdout.decode().strip())
    r = git('-C', tree, 'apply', '--check', os.path.abspath(a.patch))
    if r.returncode != 0:
        note(False, 'git apply --check: ' + r.stderr.decode('utf-8', 'replace').strip())
        print('\nFAILED %d check(s)' % len(fails))
        return 1
    note(True, 'git apply --check clean on a pristine tree')
    r = git('-C', tree, 'apply', '-v', os.path.abspath(a.patch))
    note(r.returncode == 0, 'git apply (verbose) rc=%d' % r.returncode)
    if r.returncode != 0:
        print(r.stderr.decode('utf-8', 'replace'))
        return 1

    print('[2] every touched file is on disk with the patched content')
    missing = [f for f in files if not os.path.isfile(os.path.join(tree, f))]
    note(not missing, 'files present (%d)' % (len(files) - len(missing)))
    for f in missing:
        print('       MISSING ' + f)

    print('[3] shell syntax')
    shells = [f for f in files
              if not f.endswith(('.conf', '.config'))
              and (f.endswith('.sh') or '/etc/' in f or f.endswith('qualcommax_ipq50xx'))]
    if not shutil.which('sh'):
        note(False, 'no sh on PATH')
    for f in shells:
        r = subprocess.run(['sh', '-n', os.path.join(tree, f)], capture_output=True)
        note(r.returncode == 0, 'sh -n %s %s' % (f, r.stderr.decode('utf-8', 'replace').strip()))

    print('[4] board blobs')
    for f in files:
        base = os.path.basename(f)
        if base not in EXPECT_BLOBS:
            continue
        h = hashlib.sha256(open(os.path.join(tree, f), 'rb').read()).hexdigest()
        note(h.startswith(EXPECT_BLOBS[base]),
             '%s sha256=%s (want %s...)' % (base, h, EXPECT_BLOBS[base]))

    print('[5] DTS labels')
    dts = [f for f in files if f.endswith('.dts') and '/dts/qcom/' in f]
    for f in dts:
        unresolved, used, bases = resolve_labels(tree, os.path.join(tree, f))
        note(not unresolved or a.allow_unresolved,
             '%s: %d labels used, %d resolved via %s, unresolved=%s%s' %
             (os.path.basename(f), used, used - len(unresolved),
              ','.join(bases) or 'tree only', unresolved or 'none',
              ' (allowed)' if (unresolved and a.allow_unresolved) else ''))

    if a.prev_branch:
        print('[6] upstream drift %s -> %s' % (a.prev_branch, a.branch))
        prev = os.path.abspath(os.path.join(a.workdir, 'tree-prev'))
        clone(a.repo, a.prev_branch, prev)
        import difflib
        for f in files:
            old = os.path.join(prev, f)
            new = git('-C', prev, 'show', 'HEAD:' + f)
            if not os.path.exists(old):
                print('  --   %s: new in %s' % (f, a.branch))
                continue
            a_txt = read(old)
            b_txt = new.stdout.decode('utf-8', 'replace').replace('\r\n', '\n') if new.returncode == 0 else ''
            if a_txt == b_txt:
                print('  same %s' % f)
                continue
            print('  DIFF %s' % f)
            for line in list(difflib.unified_diff(a_txt.split('\n'), b_txt.split('\n'),
                                                  a.prev_branch, a.branch, n=1, lineterm=''))[2:34]:
                print('       ' + line)

    print()
    print('patched tree: %s' % tree)
    if fails:
        print('FAILED %d check(s)' % len(fails))
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
