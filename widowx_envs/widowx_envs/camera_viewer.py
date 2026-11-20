#!/usr/bin/env python3
"""Live view of every camera topic, as a web page.

Runs inside the robonet container (it needs ROS). Start it from the host with
`python3 view_cameras.py`, which also opens the page in your browser.

    python3 camera_viewer.py                 # all image topics, http://localhost:8080
    python3 camera_viewer.py --port 8090
    python3 camera_viewer.py --topics /blue/image_raw /D435/color/image_raw
    python3 camera_viewer.py --lan           # also reachable from other machines

Every sensor_msgs/Image topic is shown in a grid with its resolution and
measured frame rate. Depth images are shown in false colour. Topics that
appear later (e.g. a camera started after the viewer) are picked up
automatically.
"""

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import rospy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

STREAM_FPS = 15        # rate at which the page is updated, per camera
JPEG_QUALITY = 80
DISCOVERY_PERIOD_S = 3.0


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
</style></head>
<body>
<h1>WidowX cameras</h1>
<div class="grid">{figures}</div>
{empty}
<script>
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
    import json
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
            html = PAGE.format(figures=figures, empty=empty, topics_json=json.dumps(topics))
            self._send(200, "text/html; charset=utf-8", html.encode())

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
    args = p.parse_args()

    rospy.init_node("camera_viewer", anonymous=True, disable_signals=True)
    viewer = Viewer(args.topics)
    threading.Thread(target=viewer.discover_forever, daemon=True).start()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, args.port), make_handler(viewer))
    server.daemon_threads = True
    print(f"Camera viewer at http://localhost:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        rospy.signal_shutdown("camera viewer stopped")


if __name__ == "__main__":
    main()
