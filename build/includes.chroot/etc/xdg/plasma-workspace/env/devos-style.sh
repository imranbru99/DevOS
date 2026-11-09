# Do NOT set QT_STYLE_OVERRIDE. Breeze + ColorScheme keeps Settings buttons
# readable; forcing Kvantum painted dark buttons on light pages.
export QT_QPA_PLATFORMTHEME=kde
# No "KDE Crash Handler" windows: DevOS shows its own name only.
export KDE_DEBUG=1
# English UI/formats for Plasma (Bangla typing does not need LC_TIME=bn_*).
export LANG=en_US.UTF-8
export LANGUAGE=en_US:en
unset LC_ALL 2>/dev/null || true
export LC_CTYPE=en_US.UTF-8
export LC_NUMERIC=en_US.UTF-8
export LC_TIME=en_US.UTF-8
export LC_COLLATE=en_US.UTF-8
export LC_MONETARY=en_US.UTF-8
export LC_MESSAGES=en_US.UTF-8
export LC_PAPER=en_US.UTF-8
export LC_NAME=en_US.UTF-8
export LC_ADDRESS=en_US.UTF-8
export LC_TELEPHONE=en_US.UTF-8
export LC_MEASUREMENT=en_US.UTF-8
export LC_IDENTIFICATION=en_US.UTF-8
