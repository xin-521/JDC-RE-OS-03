#!/usr/bin/env python3
"""Run a command (or a local script, with @path) on the router over SSH.

    python tools/ssh_run.py 'ubus call system board'
    python tools/ssh_run.py @tools/router_probe.sh 60

Credentials come from the environment: ROUTER_HOST (default 192.168.1.1),
ROUTER_USER (root), ROUTER_PASS (falls back to $G88888888a).

READ-ONLY BY CONVENTION: the router is the network's only uplink, and `make`
style long jobs on it are not worth the risk.  Nothing here should write to
flash; the probe script is read-only and `test_sysupgrade.py` only runs
`sysupgrade -T`, which validates an image without flashing it.
"""
import os
import sys

import paramiko

HOST = os.environ.get("ROUTER_HOST", "192.168.1.1")
USER = os.environ.get("ROUTER_USER", "root")
PASS = os.environ.get("ROUTER_PASS", os.environ.get("G88888888a", "G88888888a."))

arg = sys.argv[1] if len(sys.argv) > 1 else "echo hi"
if arg.startswith("@"):
    with open(arg[1:], "r", encoding="utf-8") as f:
        cmd = f.read()
else:
    cmd = arg
timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=20,
            look_for_keys=False, allow_agent=False)
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=True)
out = stdout.read().decode("utf-8", "replace")
err = stderr.read().decode("utf-8", "replace")
rc = stdout.channel.recv_exit_status()
sys.stdout.write(out)
if err.strip():
    sys.stdout.write("\n[stderr]\n" + err)
sys.stdout.write("\n[rc=%d]\n" % rc)
ssh.close()
