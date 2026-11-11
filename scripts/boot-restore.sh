#!/usr/bin/env bash
# Bring the whole desk back after the machine was off.
#
#   bash scripts/boot-restore.sh              run it now
#   bash scripts/boot-restore.sh --install    run it at every login (LaunchAgent)
#   bash scripts/boot-restore.sh --uninstall  stop doing that
#   bash scripts/boot-restore.sh --status     is it installed, and what did it do last time
#
# WHAT A REBOOT ACTUALLY TAKES. tmux keeps every session, window, pane and scrollback inside the
# tmux server process. Nothing about that is on disk, and nothing on this machine restarted it:
# checked 2026-09-20 — no tmux-resurrect or continuum (~/.tmux/plugins does not exist, no
# @resurrect-* in ~/.tmux.conf), no tmux LaunchAgent, no tmux line in ~/.zshrc or ~/.zprofile. After
# that morning's boot all five branches read "not queued".
#
# WHAT THIS DOES NOT DO. It does not restore conversations. `claude` is relaunched fresh, which is
# AGENTS.md's deliberate design — the charter and the handoff log are the memory, not the transcript.
# What it adds is that a fresh pane no longer starts green: scripts/agent-brief.sh hands it what was
# in flight, generated from git and the handoff log.
#
# It restarts exactly the pairs that were live when the machine went away, from the `.live` markers
# --start wrote. A pair the operator stopped stays stopped.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_ROOT="$(cd "$ROOT/.." && pwd)"
LOG="$DEV_ROOT/rms-audit/.state/boot-restore.log"
PLIST="$HOME/Library/LaunchAgents/com.igad.boot-restore.plist"
LABEL="com.igad.boot-restore"

# A LaunchAgent starts with a near-empty PATH — it does not read ~/.zshrc. Name every directory the
# restore needs: the claude shim, tmux and node. A missing one here fails as "claude CLI not on PATH"
# minutes after login, with nobody watching.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

mkdir -p "$(dirname "$LOG")"
# Everything goes to stdout and NOTHING writes $LOG directly. The plist captures stdout into $LOG,
# so an unattended run is recorded and an interactive run prints to the terminal. The first version
# did both — tee to $LOG plus StandardOutPath pointing at the same file — and every line in the log
# appeared twice, while `devtmux build >>$LOG` went to the file even when a person was watching.
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

install_agent() {
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/boot-restore.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null
  launchctl load "$PLIST" || { echo "launchctl load failed" >&2; return 1; }
  # Report what launchctl SAYS, not what we asked it to do — an accepted load is not a listed job.
  if launchctl list | grep -q "$LABEL"; then
    echo "installed and loaded: $PLIST"
    launchctl list | grep "$LABEL" | sed 's/^/  /'
  else
    echo "WARNING: loaded without error but '$LABEL' is not in launchctl list" >&2; return 1
  fi
}

uninstall_agent() {
  launchctl unload "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  launchctl list | grep -q "$LABEL" && { echo "WARNING: still listed after unload" >&2; return 1; }
  echo "removed: $PLIST — the grid will no longer come back by itself"
}

status_agent() {
  if [ -f "$PLIST" ]; then echo "plist: $PLIST"; else echo "plist: NOT installed"; fi
  if launchctl list | grep -q "$LABEL"; then launchctl list | grep "$LABEL" | sed 's/^/loaded: /'; else echo "loaded: no"; fi
  echo "log:   $LOG"
  [ -f "$LOG" ] && { echo "--- last run ---"; tail -20 "$LOG"; }
}

case "${1:-}" in
  --install)   install_agent; exit $? ;;
  --uninstall) uninstall_agent; exit $? ;;
  --status)    status_agent; exit 0 ;;
  "")          ;;
  *) echo "usage: $(basename "$0") [--install|--uninstall|--status]" >&2; exit 1 ;;
esac

# ---- the restore itself -------------------------------------------------------
log "=== boot restore ==="

# At login the home directory can still be mounting. Wait for the repo rather than failing on it; a
# restore that runs 30s late is fine, one that runs against a missing worktree is not.
i=0
while [ ! -d "$ROOT/.git" ] && [ "$i" -lt 30 ]; do sleep 2; i=$((i+1)); done
[ -d "$ROOT/.git" ] || { log "ABORT: $ROOT is not a git repo after $((i*2))s"; exit 1; }

command -v tmux >/dev/null 2>&1 || { log "ABORT: tmux not on PATH ($PATH)"; exit 1; }

# No devtmux here, deliberately: devtmux builds the markets session. This grid is self-contained
# in the `igad` tmux session and must not start, or depend on, anything from another project.

log "agents --restore"
bash "$ROOT/scripts/tmux-agents.sh" --restore 2>&1
log "agents --restore exited $?"

# Say what is actually running, not what was asked for. CLAUDE.md rule 11: the request is not the
# result, and this log is the only witness to a restore nobody was awake for.
log "--- panes now live ---"
tmux list-panes -a -F '#{session_name}:#{window_name}  #{pane_current_command}' 2>&1
log "=== done ==="
