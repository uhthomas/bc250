#!/usr/bin/env bash
set -euo pipefail

if (( $# != 0 )); then
    echo 'Usage: sudo bc250-cpu-unlock (then reboot manually)' >&2
    exit 2
fi
if (( EUID != 0 )); then
    echo 'Run with sudo.' >&2
    exit 1
fi
if [[ -z "$(lspci -Dn -d 1002:13fe)" ]]; then
    echo 'BC-250 GPU (1002:13fe) not detected; refusing the CPU unlock.' >&2
    exit 1
fi

# Serialize invocations, and stop the governor sharing the SMU mailbox.
exec 9>/run/lock/bc250-cpu-unlock.lock
flock --nonblock 9
restart_governor=false
if systemctl is-active --quiet cyan-skillfish-governor-smu.service; then
    restart_governor=true
fi
restore_governor() {
    if "$restart_governor"; then
        systemctl start cyan-skillfish-governor-smu.service
    fi
}
trap restore_governor EXIT
systemctl stop cyan-skillfish-governor-smu.service

# Upstream refuses unexpected masks. No force option and no automatic reboot.
python3 /usr/share/bc250/vendor/cpu-unlock/bc250-unlock-cores.py
echo 'Reboot manually to enumerate the extra cores. Cold power-off clears this unlock.'
