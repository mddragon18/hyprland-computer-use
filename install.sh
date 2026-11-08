#!/bin/sh
# Build the pointer helper and install the Hyprland computer-use provider.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
plugin="$here/plugin/hyprland"
dest="${HERMES_HOME:-$HOME/.hermes}/plugins"

for tool in make cc pkg-config; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "missing build tool: $tool" >&2
        echo "On Arch: sudo pacman -S --needed base-devel pkgconf wayland" >&2
        exit 1
    fi
done
if ! pkg-config --exists wayland-client; then
    echo "missing wayland-client development headers" >&2
    echo "On Arch: sudo pacman -S --needed wayland" >&2
    exit 1
fi

echo "==> building pointer helper"
make -C "$plugin/pointer"

echo "==> linking provider into $dest"
mkdir -p "$dest"
ln -sfn "$plugin" "$dest/hyprland"

cat <<EOF

Installed $dest/hyprland

Add to ${HERMES_HOME:-$HOME/.hermes}/config.yaml:

  platform_toolsets:
    cli:
      - ...
      - computer_use
      - ...

  computer_use:
    backend: hyprland

Then run:

  hermes computer-use doctor
EOF
