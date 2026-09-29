#!/usr/bin/env bash
# APC AP7921B, MAC 28:29:86:37:28:d2, discovered at 192.168.0.53.
# CLI reference: https://www.se.com/ph/en/faqs/FA156163/
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: ./apc-reboot-outlet-8.sh [--status|--off|--on]

With no arguments, immediately power-cycle outlet 8 on the discovered APC PDU.
--status checks login, outlet status and grouping without changing power.
--off and --on set outlet 8 explicitly for isolated recovery trials.
Requires OpenSSH and Expect. Defaults: APC_HOST=192.168.0.53,
APC_USERNAME=apc, APC_PASSWORD=apc (all overridable environment variables).
The SSH host key is pinned to the discovered PDU, even if its IP changes.
HELP
}

if (( $# > 1 )); then
    usage >&2
    exit 2
fi
case "${1-}" in
    '') export APC_ACTION=reboot ;;
    --status) export APC_ACTION=status ;;
    --off) export APC_ACTION=off ;;
    --on) export APC_ACTION=on ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

for dependency in ssh expect; do
    if ! command -v "$dependency" >/dev/null; then
        printf 'Required command not found: %s\n' "$dependency" >&2
        exit 1
    fi
done

export APC_HOST="${APC_HOST:-192.168.0.53}"
export APC_USERNAME="${APC_USERNAME:-apc}"
export APC_PASSWORD="${APC_PASSWORD:-apc}"
APC_KNOWN_HOSTS=$(mktemp)
export APC_KNOWN_HOSTS
trap 'rm -f -- "$APC_KNOWN_HOSTS"' EXIT
# Public host key observed during discovery on 2026-09-24.
cat >"$APC_KNOWN_HOSTS" <<'KEY'
bc250-apc-pdu ssh-rsa AAAAB3NzaC1yc2EAAAACAQEAAAEBAK6BX7lod67nK3LLMK172NtQ/TDWx82TWmx+HJvcCthAoxE3IEN35VnjBxYfBwnTwKb6770Y7G+R/MRm5gBEtxyfzz2yPaL2Al1ZQC0uM8iV6bKxH3hD8xUhi17ccjxE2kmwPBXHUpQTlWvQcINOFd3/PTwb7JlYZt08B7Uo/GVgCPn++mF9OIItfmCMwXS0PaIBoGANvpV247W5gvmSTdcaGakizuwmIN4zYbjsIXswFenUETTTNWdgGh4E35pRfxRwreNNcuepAqSE7umNzpHPa1+aM5yUVcAJAT6wYPES6GK1qJUlT0kHkvo8t/GNq/txpCVJVKUnMLNQ3kqBmFU=
KEY

expect <<'EXPECT'
set timeout 20
log_user 0

proc fail {message} {
    puts stderr $message
    exit 1
}

proc prompt {context} {
    global spawn_id timeout expect_out
    expect {
        -re {(?n)(^|\n)apc>[ \t]*$} {
            return [string map [list "\r" ""] $expect_out(buffer)]
        }
        timeout { fail "Timed out $context." }
        eof { fail "Connection closed $context: $expect_out(buffer)" }
    }
}

proc command {text} {
    global spawn_id
    send -- "$text\r"
    set context "waiting for '$text'"
    if {$text eq "olReboot 8"} {
        append context "; reboot outcome is unknown, check --status before retrying"
    }
    set response [prompt $context]
    if {![regexp {(?n)^E000: Success[ \t]*$} $response] ||
        [regexp {(?n)^E[1-9][0-9][0-9]:} $response]} {
        fail "PDU did not confirm '$text':\n$response"
    }
    return $response
}

# Only this SSH invocation enables the legacy host-key algorithm.
spawn -noecho ssh -F /dev/null -tt \
    -o ConnectTimeout=10 -o ConnectionAttempts=1 \
    -o HostKeyAlgorithms=+ssh-rsa -o HostKeyAlias=bc250-apc-pdu \
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$env(APC_KNOWN_HOSTS)" \
    -o GlobalKnownHostsFile=/dev/null -o UpdateHostKeys=no \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    -o NumberOfPasswordPrompts=1 -o LogLevel=ERROR \
    -l $env(APC_USERNAME) -- $env(APC_HOST)
expect {
    -nocase -re {password:[ \t]*$} { send -- "$env(APC_PASSWORD)\r" }
    timeout { fail "Timed out waiting for the SSH password prompt." }
    eof { fail "SSH connection failed: $expect_out(buffer)" }
}
prompt "logging in"

set status [command "olStatus 8"]
if {![regexp -nocase -line {^[ \t]*(8:[^\n]*: (On|Off))[ \t]*$} $status _ outlet]} {
    fail "Unexpected outlet 8 status:\n$status"
}
puts "$env(APC_HOST): $outlet"

set groups [command "olGroups"]
if {![string match {*Device outlet group configuration is DISABLED.*} $groups]} {
    fail "Outlet grouping is enabled or unknown; refusing to risk cycling other outlets.\n$groups"
}
puts "Outlet grouping: disabled"

if {$env(APC_ACTION) eq "reboot"} {
    command "olReboot 8"
    puts "Outlet 8 reboot accepted by the PDU."
} elseif {$env(APC_ACTION) eq "off"} {
    command "olOff 8"
    puts "Outlet 8 off accepted by the PDU."
} elseif {$env(APC_ACTION) eq "on"} {
    command "olOn 8"
    puts "Outlet 8 on accepted by the PDU."
} else {
    puts "Status check complete; no power changes made."
}

send -- "exit\r"
expect {
    eof {}
    timeout { catch {close} }
}
EXPECT
