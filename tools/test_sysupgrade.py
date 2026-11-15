#!/usr/bin/env python3
"""Validate a sysupgrade image on the live router WITHOUT flashing it.

    python tools/test_sysupgrade.py --yes <image.bin>

What it does: streams the image to /tmp on the router, compares sha256, runs
`sysupgrade -T` (test mode: it checks the tar layout, the metadata
supported_devices list against /tmp/sysinfo/board_name, and the image type), then
deletes the upload again.  No flash partition is written.

Why the caution: the box is the only uplink, /tmp is tmpfs (about 215MB), and
the overlay is small -- a mistyped path once landed a 22MB image on the overlay
root.  So: --yes is mandatory, the remote path must sit directly under /tmp,
free space is checked first, and cleanup runs even if the test fails.

`sysupgrade -T` passing means `sysupgrade` would accept the file: board match,
tar structure, metadata.  It says nothing about the image being *good* — that is
what the CI's build + verify steps are for.
"""
import argparse
import hashlib
import os
import posixpath
import sys

import paramiko

HOST = os.environ.get("ROUTER_HOST", "192.168.1.1")
USER = os.environ.get("ROUTER_USER", "root")
PASS = os.environ.get("ROUTER_PASS", os.environ.get("G88888888a", "G88888888a."))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--yes', action='store_true', help='required: this uploads to the device')
    ap.add_argument('--keep', action='store_true', help='leave the upload in /tmp')
    a = ap.parse_args()

    if not a.yes:
        sys.exit('refusing to touch the router without --yes '
                 '(the box is the network uplink; read the docstring first)')
    if not os.path.isfile(a.image):
        sys.exit('no such image: ' + a.image)

    remote = posixpath.join('/tmp', os.path.basename(a.image))
    if posixpath.dirname(remote) != '/tmp':
        sys.exit('remote path must be /tmp/<file>, got ' + remote)

    size = os.path.getsize(a.image)
    local = sha256(a.image)
    print('local  %s  %d bytes' % (local, size))

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=20,
                look_for_keys=False, allow_agent=False)

    def run(cmd, timeout=600):
        _, out, err = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
        return (out.read().decode('utf-8', 'replace') +
                err.read().decode('utf-8', 'replace'),
                out.channel.recv_exit_status())

    try:
        txt, _ = run("df -k /tmp | tail -1; grep MemFree /proc/meminfo | head -1")
        print('device ' + txt.strip())
        free_kb = int(txt.split('\n')[0].split()[3])
        if free_kb * 1024 < size + (8 << 20):
            sys.exit('not enough /tmp space: %d KiB free for a %d byte image' % (free_kb, size))

        print('uploading to ' + remote)
        chan = ssh.get_transport().open_session()
        chan.exec_command('cat > %s' % remote)
        with open(a.image, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 16), b''):
                chan.sendall(chunk)
        chan.shutdown_write()
        if chan.recv_exit_status() != 0:
            sys.exit('upload failed')

        txt, _ = run('sha256sum %s' % remote)
        print('device ' + txt.strip())
        if not txt.startswith(local):
            sys.exit('sha256 mismatch: the upload is corrupt, not testing it')

        print('== sysupgrade -T (test only, nothing is flashed) ==')
        txt, rc = run('sysupgrade -T %s 2>&1; echo RC=$?' % remote)
        print(txt.rstrip())
        print('sysupgrade -T exit=%d' % rc)
    finally:
        if a.keep:
            print('kept %s on the device (--keep)' % remote)
        else:
            txt, _ = run('rm -f %s; ls %s 2>/dev/null || echo removed' % (remote, remote))
            print('cleanup: ' + txt.strip())
        ssh.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
