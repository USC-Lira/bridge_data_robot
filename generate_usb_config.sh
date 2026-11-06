#!/bin/bash
#
# Write usb_connector_chart.yml: one "<topic>: '<usb path>'" line per USB webcam
# that multicam_server should stream.
#
#   ./generate_usb_config.sh                 # writes ./usb_connector_chart.yml
#   ./generate_usb_config.sh path/to/out.yml
#
# Only cameras that are actually plugged in get a line. An empty value would be
# worse than no line at all: start_streamers.py matches values against
# `v4l2-ctl --list-devices` with a substring test, and '' matches the first
# device, silently publishing the wrong camera under that topic.
#
# The RealSense is written too, under the D435 key, as the original script did.
# Note that widowx_rs.launch also starts the realsense2_camera nodelet for it,
# so multicam_server opens the same device a second time as a plain webcam
# (publishing /D435/image_raw next to the nodelet's /D435/color/...). Kept for
# now to test whether the rig behaves better with it; see docs/preflight.md.
#
# preflight.py runs this script for you on every run and reports the result.

set -euo pipefail

out="${1:-usb_connector_chart.yml}"

if ! command -v v4l2-ctl >/dev/null 2>&1; then
    echo "v4l2-ctl not found: sudo apt install v4l-utils" >&2
    exit 1
fi

blue=""
yellow=""
wrist=""
d435=""

# Header lines look like "1080P Pro Stream (usb-0000:00:14.0-9.1):". Take the
# LAST parenthesised part: the RealSense name itself contains "(R)" and "(TM)".
usb_path() {
    echo "$1" | sed 's/.*(\(.*\)).*/\1/'
}

# v4l2-ctl exits non-zero if some node cannot be opened but still lists the
# rest, so do not let that abort the script.
devices="$(v4l2-ctl --list-devices 2>/dev/null || true)"

while IFS= read -r line; do
    if [[ $line == *"Piwebcam: UVC Camera"* ]]; then
        wrist=$(usb_path "$line")
    elif [[ $line == *"1080P Pro Stream"* ]] && [ -z "$blue" ]; then
        blue=$(usb_path "$line")
    elif [[ $line == *"1080P Pro Stream"* ]]; then
        yellow=$(usb_path "$line")
    elif [[ $line == *"Intel(R) RealSense(TM) Depth Ca"* ]]; then
        d435=$(usb_path "$line")
    fi
done <<< "$devices"

# Write to a temp file and rename, so a failure never leaves a half-written chart.
tmp="$(mktemp "${out}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
{
    if [ -n "$blue" ]; then echo "blue: '$blue'"; fi
    if [ -n "$yellow" ]; then echo "yellow: '$yellow'"; fi
    if [ -n "$wrist" ]; then echo "wrist: '$wrist'"; fi
    if [ -n "$d435" ]; then echo "D435: '$d435'"; fi
    # An empty file loads as None in start_streamers.py; {} loads as an empty dict.
    if [ -z "$blue$yellow$wrist$d435" ]; then echo "{}"; fi
} > "$tmp"
chmod 644 "$tmp"  # mktemp creates 0600; the container reads this via a bind mount
mv "$tmp" "$out"
trap - EXIT

found=$(grep -c ":" "$out" || true)
echo "wrote $out ($found camera(s))"
