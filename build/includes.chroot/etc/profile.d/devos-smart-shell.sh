# Optional DevOS Smart Shell hints after failed commands.
# Enable per-user:  echo 'eval "$(devos heal --hook)"' >> ~/.bashrc
# Or:              export DEVOS_SMART_SHELL=1
if [ -n "${DEVOS_SMART_SHELL:-}" ] && [ -z "${DEVOS_SMART_SHELL_LOADED:-}" ]; then
  DEVOS_SMART_SHELL_LOADED=1
  if command -v devos >/dev/null 2>&1; then
    eval "$(devos heal --hook 2>/dev/null)" || true
  fi
fi
