#!/usr/bin/env python3
"""Pi 5 user-timer PDU client for BC250 outlet 8, with a pinned SSH host key.

Stage beside the repository's apc-reboot-outlet-8.sh, whose existing pinned
host-key line is reused. Install pexpect on the Pi (Raspberry Pi OS includes it).
Use ``systemd-run --user --on-active=3min`` to schedule ``--reboot``; verify
the timer is active before an experimental BC250 SMU command, and stop the
timer only after the experiment has finished or the board has been recovered.
"""

import argparse
import os
from pathlib import Path
import re
import tempfile

import pexpect

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / 'apc-reboot-outlet-8.sh'
OUTLET = '8'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def pinned_key():
    lines = [line.strip() for line in REFERENCE.read_text().splitlines()
             if line.startswith('bc250-apc-pdu ssh-rsa ')]
    require(len(lines) == 1, 'expected one pinned PDU SSH host key')
    return lines[0] + '\n'


def command(child, text):
    child.sendline(text)
    child.expect(r'(?m)(?:^|\r?\n)apc>[ \t]*$')
    response = child.before.replace('\r', '')
    require(re.search(r'(?m)^E000: Success[ \t]*$', response),
            f'PDU did not confirm {text!r}: {response!r}')
    require(not re.search(r'(?m)^E[1-9][0-9][0-9]:', response),
            f'PDU returned an error for {text!r}: {response!r}')
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true',
                        help='read outlet and group state without changing power')
    parser.add_argument('--reboot', action='store_true',
                        help='cold-cycle only outlet 8 after all guards pass')
    args = parser.parse_args()
    require(args.status != args.reboot, 'select exactly one action')
    with tempfile.TemporaryDirectory(prefix='bc250-pdu-key-') as directory:
        known_hosts = Path(directory) / 'known_hosts'
        known_hosts.write_text(pinned_key())
        known_hosts.chmod(0o600)
        ssh_args = ['-F', '/dev/null', '-tt', '-o', 'ConnectTimeout=10',
                    '-o', 'ConnectionAttempts=1', '-o', 'HostKeyAlgorithms=+ssh-rsa',
                    '-o', 'HostKeyAlias=bc250-apc-pdu',
                    '-o', 'StrictHostKeyChecking=yes',
                    '-o', f'UserKnownHostsFile={known_hosts}',
                    '-o', 'GlobalKnownHostsFile=/dev/null',
                    '-o', 'UpdateHostKeys=no',
                    '-o', 'PreferredAuthentications=password',
                    '-o', 'PubkeyAuthentication=no',
                    '-o', 'NumberOfPasswordPrompts=1',
                    '-o', 'LogLevel=ERROR', '-l', os.getenv('APC_USERNAME', 'apc'),
                    '--', os.getenv('APC_HOST', '192.168.0.53')]
        child = pexpect.spawn('ssh', ssh_args, encoding='utf-8', timeout=20)
        try:
            child.expect(r'(?i)password:[ \t]*$')
            child.sendline(os.getenv('APC_PASSWORD', 'apc'))
            child.expect(r'(?m)(?:^|\r?\n)apc>[ \t]*$')
            status = command(child, f'olStatus {OUTLET}')
            match = re.search(r'(?m)^[ \t]*8: Outlet 8: (On|Off)[ \t]*$', status)
            require(match is not None, f'unexpected outlet-8 status: {status!r}')
            print(f'Outlet 8: {match.group(1)}', flush=True)
            groups = command(child, 'olGroups')
            require('Device outlet group configuration is DISABLED' in groups,
                    'PDU outlet grouping is enabled or unknown')
            print('Outlet grouping: disabled', flush=True)
            if args.reboot:
                require(match.group(1) == 'On', 'outlet 8 was not on')
                command(child, f'olReboot {OUTLET}')
                print('Outlet 8 reboot accepted', flush=True)
            else:
                print('Status check complete; no power change', flush=True)
        finally:
            try:
                child.sendline('exit')
                child.expect(pexpect.EOF, timeout=5)
            except (pexpect.EOF, pexpect.TIMEOUT):
                child.close(force=True)


if __name__ == '__main__':
    main()
