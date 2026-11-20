#!/usr/bin/env python3
"""Live view of every camera topic, as a web page.

Runs inside the robonet container (it needs ROS). Start it from the host with
`python3 view_cameras.py`, which also opens the page in your browser.

    python3 camera_viewer.py                 # all image topics, http://localhost:8080
    python3 camera_viewer.py --port 8090
    python3 camera_viewer.py --topics /blue/image_raw /D435/color/image_raw
    python3 camera_viewer.py --lan           # also reachable from other machines
    python3 camera_viewer.py --during-collection

Every sensor_msgs/Image topic is shown in a grid with its resolution and
measured frame rate. Depth images are shown in false colour. Topics that
appear later (e.g. a camera started after the viewer) are picked up
automatically.

It does not run during data collection unless --during-collection is given:
it refuses to start while run_data_collection.py runs, and closes itself if
collection starts.

Swapping cameras: if two webcams of the same model (blue and yellow) are in
each other's place, the page offers a swap button. It swaps their entries in
the usb connector chart and restarts only the webcam streams (the arm driver
keeps running). Preflight keeps that assignment while the cameras stay on the
same USB ports. With --during-collection, swapping stays possible until the
session records its first episode, then it is disabled. Swapping is only
possible from the Alienware itself (not with --lan from another machine).
"""

import argparse
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import rospy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

CHART_PATH = "/tmp/camera_connector_chart"   # usb_connector_chart.yml, mounted by docker-compose.yml
RESTART_LOG = "/tmp/camera_streams_restart.log"
# Written by VR_WidowX (its process id) when a session records its first episode.
RECORDING_MARKER = "/tmp/widowx_collection_recording"
STREAM_FPS = 15        # rate at which the page is updated, per camera
JPEG_QUALITY = 80
DISCOVERY_PERIOD_S = 3.0


# --------------------------------------------------------------------------- #
# data collection guard
# --------------------------------------------------------------------------- #


def collection_pids():
    """Process ids of run_data_collection.py in this container."""
    me, pids = os.getpid(), []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"run_data_collection.py" in f.read():
                    pids.append(int(pid))
        except OSError:
            continue
    return pids


def collection_running() -> bool:
    return bool(collection_pids())


def recording_started() -> bool:
    """Whether the running collection session has started recording episodes.

    The marker holds the process id of the session that wrote it, so a marker
    left by an earlier session does not count.
    """
    try:
        with open(RECORDING_MARKER) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    return pid in collection_pids()


def swap_blocked_reason():
    """Why swapping is not allowed right now, or None."""
    if collection_running() and recording_started():
        return ("data collection has started recording episodes: swapping cameras now would mix "
                "them up in the dataset")
    return None


# --------------------------------------------------------------------------- #
# camera assignment (usb connector chart)
# --------------------------------------------------------------------------- #


def read_chart():
    chart = {}
    try:
        with open(CHART_PATH) as f:
            for raw in f:
                line = raw.split("#", 1)[0].strip()
                if ":" in line and not line.startswith("{"):
                    key, _, value = line.partition(":")
                    chart[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return chart


def write_chart(chart):
    # Write in place: the chart is a single bind-mounted file, a rename would
    # not reach the host.
    with open(CHART_PATH, "w") as f:
        f.write("".join(f"{k}: '{v}'\n" for k, v in chart.items()) if chart else "{}\n")


def camera_models(chart):
    """{chart key: v4l2 model name}, e.g. {'blue': '1080P Pro Stream'}."""
    try:
        out = subprocess.run(["v4l2-ctl", "--list-devices"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    headers = [l.strip() for l in out.splitlines() if l.strip() and not l[0].isspace()]
    models = {}
    for key, usb_path in chart.items():
        for h in headers:
            if usb_path and usb_path in h:
                models[key] = h.split(" (")[0]
    return models


def swappable_pairs(chart):
    """Pairs of chart keys whose cameras are the same model (only those can be mixed up)."""
    models = camera_models(chart)
    keys = [k for k in chart if k in models]
    return [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if models[a] == models[b]]


def restart_webcam_streams(chart_keys):
    """Restart multicam_server's webcam streams with the current chart.

    Only the camera streamer and the stream nodes under each camera's
    namespace are stopped; the arm driver and the RealSense keep running.
    start_streamers.py hard-kills its roslaunch children, so the stream nodes
    themselves are stopped too, or they would keep /dev/video* busy.
    """
    import rosnode

    nodes = rosnode.get_node_names()
    targets = [n for n in nodes if n.rstrip("/").endswith("/camera_stream")]
    targets += [n for n in nodes
                if any(n.startswith(f"/{k}/") for k in chart_keys) or "/streamer_" in n]
    if targets:
        rosnode.kill_nodes(targets)
    time.sleep(3)  # let the devices be released
    with open(RESTART_LOG, "w") as log:
        subprocess.Popen(
            ["roslaunch", "multicam_server", "cameras.launch", f"camera_connector_chart:={CHART_PATH}"],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    return targets


def swap_cameras(a, b):
    """Swap two chart entries and restart the webcam streams. Returns a message."""
    reason = swap_blocked_reason()
    if reason:
        raise ValueError(reason)
    chart = read_chart()
    if a not in chart or b not in chart:
        raise ValueError(f"{a} and {b} must both be in the usb connector chart")
    if (a, b) not in swappable_pairs(chart) and (b, a) not in swappable_pairs(chart):
        raise ValueError(f"{a} and {b} are not the same camera model, so they cannot be mixed up")
    chart[a], chart[b] = chart[b], chart[a]
    write_chart(chart)
    rospy.loginfo("camera viewer: swapped %s and %s in the chart: %s", a, b, chart)
    restart_webcam_streams(list(chart))
    return (f"Swapped {a} and {b}. The webcam streams are restarting; they take about 10 s to come "
            "back. Preflight keeps this assignment while the cameras stay on the same USB ports.")


class CameraFeed:
    """Latest frame of one topic, kept as a JPEG for the page."""

    def __init__(self, topic):
        self.topic = topic
        self.bridge = CvBridge()
        self.lock = threading.Lock()
        self.jpeg = None
        self.info = "waiting for frames..."
        self.stamps = []
        self.sub = rospy.Subscriber(topic, Image, self._on_image, queue_size=1, buff_size=2 ** 24)

    def _on_image(self, msg):
        now = time.time()
        self.stamps = [t for t in self.stamps if now - t < 2.0] + [now]
        fps = (len(self.stamps) - 1) / (self.stamps[-1] - self.stamps[0]) if len(self.stamps) > 1 else 0.0
        try:
            img = self._to_bgr(msg)
        except Exception as exc:  # unusual encodings should not kill the viewer
            with self.lock:
                self.info = f"cannot display {msg.encoding}: {exc}"
            return
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            with self.lock:
                self.jpeg = buf.tobytes()
                self.info = f"{msg.width}x{msg.height} {msg.encoding}, {fps:.1f} fps"

    def _to_bgr(self, msg):
        if msg.encoding in ("16UC1", "32FC1", "mono16"):
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough").astype(np.float32)
            valid = depth[np.isfinite(depth) & (depth > 0)]
            hi = np.percentile(valid, 99) if valid.size else 1.0
            scaled = np.clip(np.nan_to_num(depth) / max(hi, 1e-6) * 255, 0, 255).astype(np.uint8)
            return cv2.applyColorMap(scaled, cv2.COLORMAP_JET)
        return self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

    def snapshot(self):
        with self.lock:
            return self.jpeg, self.info


class Viewer:
    def __init__(self, topics=None):
        self.fixed_topics = topics
        self.feeds = {}
        self.lock = threading.Lock()

    def discover(self):
        """Subscribe to image topics that are not watched yet."""
        if self.fixed_topics:
            wanted = self.fixed_topics
        else:
            wanted = sorted(t for t, kind in rospy.get_published_topics() if kind == "sensor_msgs/Image")
        with self.lock:
            for topic in wanted:
                if topic not in self.feeds:
                    rospy.loginfo("camera viewer: watching %s", topic)
                    self.feeds[topic] = CameraFeed(topic)

    def discover_forever(self):
        while not rospy.is_shutdown():
            try:
                self.discover()
            except Exception as exc:
                rospy.logwarn("camera viewer: topic discovery failed: %s", exc)
            time.sleep(DISCOVERY_PERIOD_S)

    def topics(self):
        with self.lock:
            return sorted(self.feeds)

    def feed(self, topic):
        with self.lock:
            return self.feeds.get(topic)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>WidowX cameras</title>
<style>
  body {{ margin: 0; padding: 16px; background: #111; color: #ddd; font: 14px system-ui, sans-serif; }}
  h1 {{ font-size: 16px; font-weight: 600; margin: 0 0 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 12px; }}
  figure {{ margin: 0; background: #000; border: 1px solid #333; }}
  img {{ display: block; width: 100%; height: auto; }}
  figcaption {{ padding: 6px 8px; font-family: ui-monospace, monospace; font-size: 12px; }}
  .info {{ color: #8a8; float: right; }}
  .empty {{ color: #aaa; }}
  .panel {{ margin: 0 0 12px; padding: 8px 10px; border: 1px solid #333; background: #1a1a1a; }}
  .panel code {{ color: #ccc; }}
  button {{ margin: 4px 8px 0 0; padding: 6px 10px; background: #2b4a6b; color: #fff; border: 0; cursor: pointer; }}
  button:disabled {{ background: #444; color: #999; cursor: not-allowed; }}
  .note {{ color: #999; font-size: 12px; }}
</style></head>
<body>
<h1>WidowX cameras</h1>
{assignment}
<div class="grid">{figures}</div>
{empty}
<script>
  async function swap(a, b) {{
    if (!confirm("Swap " + a + " and " + b + "? The webcam streams restart (about 10 s); the arm keeps running.")) return;
    const r = await fetch("/swap?a=" + encodeURIComponent(a) + "&b=" + encodeURIComponent(b), {{method: "POST"}});
    alert(await r.text());
    setTimeout(() => location.reload(), 8000);
  }}
  // Refresh the per-camera info line; reload when new topics appear.
  const known = {topics_json};
  setInterval(async () => {{
    try {{
      const r = await fetch("/status"); const s = await r.json();
      if (JSON.stringify(Object.keys(s).sort()) !== JSON.stringify(known)) location.reload();
      for (const [t, info] of Object.entries(s)) {{
        const el = document.getElementById("info-" + t); if (el) el.textContent = info;
      }}
    }} catch (e) {{}}
  }}, 1000);
</script>
</body></html>"""


def make_handler(viewer):
    from urllib.parse import quote, unquote

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._page()
            if self.path == "/status":
                status = {t: viewer.feed(t).snapshot()[1] for t in viewer.topics()}
                return self._send(200, "application/json", json.dumps(status).encode())
            if self.path.startswith("/stream"):
                return self._stream(unquote(self.path[len("/stream"):]))
            self._send(404, "text/plain", b"not found")

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _page(self):
            topics = viewer.topics()
            figures = "".join(
                f'<figure><img src="/stream{quote(t)}" alt="{t}">'
                f'<figcaption>{t}<span class="info" id="info-{t}"></span></figcaption></figure>'
                for t in topics
            )
            empty = "" if topics else '<p class="empty">No image topics yet. Is the robonet container running?</p>'
            html = PAGE.format(figures=figures, empty=empty, topics_json=json.dumps(topics),
                               assignment=self._assignment_html())
            self._send(200, "text/html; charset=utf-8", html.encode())

        def _local(self):
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _assignment_html(self):
            chart = read_chart()
            if not chart:
                return ""
            rows = ", ".join(f"<code>/{k}</code> = {v}" for k, v in chart.items())
            pairs = swappable_pairs(chart)
            if not pairs:
                return f'<div class="panel">Webcams: {rows}</div>'
            reason = ""
            if swap_blocked_reason():
                reason = "Swapping is disabled: data collection has started recording episodes."
            elif not self._local():
                reason = "Swapping is only possible on the Alienware itself."
            elif collection_running():
                reason = ""  # allowed until the first episode starts
            hint = ("Data collection is running but has not recorded anything yet: you can still swap. "
                    "Wait until the cameras are back (about 10 s) before starting the first episode."
                    if collection_running() and not reason else "")
            buttons = "".join(
                f'<button {"disabled" if reason else ""} onclick="swap(\'{a}\', \'{b}\')">Swap {a} and {b}</button>'
                for a, b in pairs
            )
            note = reason or hint or "Use this if two cameras of the same model are in each other's place."
            return f'<div class="panel">Webcams: {rows}<br>{buttons}<div class="note">{note}</div></div>'

        def do_POST(self):
            from urllib.parse import parse_qs, urlparse
            url = urlparse(self.path)
            if url.path != "/swap":
                return self._send(404, "text/plain", b"not found")
            if not self._local():
                return self._send(403, "text/plain", b"Swapping is only possible on the Alienware itself.")
            q = parse_qs(url.query)
            try:
                msg = swap_cameras(q.get("a", [""])[0], q.get("b", [""])[0])
                self._send(200, "text/plain; charset=utf-8", msg.encode())
            except Exception as exc:
                self._send(409, "text/plain; charset=utf-8", f"Not swapped: {exc}".encode())

        def _stream(self, topic):
            feed = viewer.feed(topic)
            if feed is None:
                return self._send(404, "text/plain", b"unknown topic")
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = None
            try:
                while not rospy.is_shutdown():
                    jpeg, _ = feed.snapshot()
                    if jpeg is not None and jpeg is not last:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                        last = jpeg
                    time.sleep(1.0 / STREAM_FPS)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser closed the page

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--topics", nargs="+", help="only these image topics (default: all)")
    p.add_argument("--lan", action="store_true",
                   help="listen on all interfaces, so other machines on the network can view it")
    p.add_argument("--during-collection", action="store_true",
                   help="allow running while data collection runs (otherwise it refuses to start, "
                   "and closes itself when collection starts)")
    args = p.parse_args()

    if collection_running() and not args.during_collection:
        print("Data collection is running. The camera viewer does not run during collection unless\n"
              "you ask for it: add --during-collection.", flush=True)
        raise SystemExit(3)

    rospy.init_node("camera_viewer", anonymous=True, disable_signals=True)
    viewer = Viewer(args.topics)
    threading.Thread(target=viewer.discover_forever, daemon=True).start()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(viewer))
    server.daemon_threads = True
    print(f"Camera viewer at http://localhost:{args.port}  (Ctrl+C to stop)", flush=True)

    if not args.during_collection:
        def close_when_collection_starts():
            while True:
                time.sleep(2)
                if collection_running():
                    print("Data collection started: closing the camera viewer "
                          "(use --during-collection to keep it open).", flush=True)
                    server.shutdown()
                    return
        threading.Thread(target=close_when_collection_starts, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        rospy.signal_shutdown("camera viewer stopped")


if __name__ == "__main__":
    main()
