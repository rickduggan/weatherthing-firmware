#!/usr/bin/env python3
"""Stream a video (YouTube URL, file, or any URL ffmpeg/yt-dlp understands) to the
weatherthing Video card as 20x7 RGB frames over UDP port 4210. The sound plays
through this machine's default audio output. Plays at 2x speed unless --speed says otherwise.

  wt-stream.py https://www.youtube.com/watch?v=...            # host defaults to weatherthing.local
  wt-stream.py clip.mp4 --host 192.168.37.147 --fps 15
  wt-stream.py URL --speed 1 --mute                            # normal speed, no sound
  wt-stream.py --test                                          # colour sweep, no video needed

Needs ffmpeg, and yt-dlp for YouTube. Select the Video card on the device first.
"""
import argparse, socket, subprocess, sys, time, urllib.request

W, H = 20, 7
FRAME = W * H * 3


def atempo_chain(speed):
    """atempo only accepts 0.5-2.0 per filter, so chain for larger/smaller speeds."""
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0"); speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5"); speed /= 0.5
    parts.append(f"atempo={speed:g}")
    return ",".join(parts)


def frames_from_ffmpeg(src, fps, crop, speed, audio, aa=True):
    # YouTube's signed URLs reject plain ffmpeg requests (403), so let yt-dlp do the download
    yt = src.startswith(("http://", "https://")) and "youtu" in src
    vf = [f"setpts=PTS/{speed:g}"]
    if aa:  # take twice the frames, averaged in pairs below (a little motion blur, less shimmer)
        vf.append(f"fps={fps * 2}")
    if crop:  # centre-crop to the display's aspect ratio (20:7) before scaling
        vf.append(f"crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})'")
    if aa:
        # Average each display pixel's source area in linear light, not in gamma-encoded
        # values (which makes edges and small bright details come out too dark)
        vf += ["format=gbrp16le",
               "lutrgb=r='pow(val/maxval\\,2.2)*maxval':g='pow(val/maxval\\,2.2)*maxval':b='pow(val/maxval\\,2.2)*maxval'",
               f"scale={W}:{H}:flags=area",
               "tmix=frames=2",
               "lutrgb=r='pow(val/maxval\\,1/2.2)*maxval':g='pow(val/maxval\\,1/2.2)*maxval':b='pow(val/maxval\\,1/2.2)*maxval'",
               "format=rgb24"]
    else:
        vf.append(f"scale={W}:{H}:flags=area")
    # -readrate reads the input at `speed`x real time, so the sped-up output plays in real time
    cmd = ["ffmpeg", "-loglevel", "error", "-readrate", f"{speed:g}", "-i", "pipe:0" if yt else src,
           "-map", "0:v:0", "-an", "-vf", ",".join(vf), "-r", str(fps),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    if audio:
        cmd += ["-map", "0:a:0?", "-vn", "-af", atempo_chain(speed), "-f", "pulse", "weatherthing"]
    dl = None
    if yt:
        dl = subprocess.Popen(["yt-dlp", "-q", "--no-playlist", "-f", "worst[ext=mp4]/worst", "-o", "-", src],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p = subprocess.Popen(cmd, stdin=dl.stdout if dl else None, stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(FRAME)
            if len(buf) < FRAME:
                return
            yield buf
    finally:
        p.kill()
        if dl:
            dl.kill()


def test_frames(fps):
    t = 0
    while True:
        f = bytearray()
        for y in range(H):
            for x in range(W):
                f += bytes(((x * 12 + t * 8) % 256, (y * 36 + t * 5) % 256, (255 - x * 12 + t * 3) % 256))
        yield bytes(f)
        t += 1
        time.sleep(1 / fps)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?")
    ap.add_argument("--host", default="weatherthing.local")
    ap.add_argument("--port", type=int, default=4210)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--speed", type=float, default=2.0, help="playback speed (default 2)")
    ap.add_argument("--mute", action="store_true", help="don't play the sound")
    ap.add_argument("--no-show", action="store_true", help="don't switch the device to the Video card first")
    ap.add_argument("--no-aa", action="store_true", help="plain scaling, without the anti-aliasing")
    ap.add_argument("--stretch", action="store_true", help="squash to 20x7 instead of centre-cropping")
    ap.add_argument("--loop", action="store_true", help="repeat when the video ends")
    ap.add_argument("--test", action="store_true", help="send a test pattern")
    a = ap.parse_args()
    if not a.source and not a.test:
        ap.error("give a source or --test")

    addr = (socket.gethostbyname(a.host), a.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if not a.no_show:
        try:  # put the device on the Video card (card 16)
            urllib.request.urlopen(f"http://{a.host}/api/card?card=16&preset=0", timeout=5).read()
        except Exception as e:
            print(f"couldn't switch the device to the Video card ({e}); select it by hand", file=sys.stderr)
    print(f"streaming to {addr[0]}:{addr[1]} at {a.fps} fps, {a.speed:g}x speed (Ctrl-C to stop)", file=sys.stderr)
    try:
        while True:
            gen = test_frames(a.fps) if a.test else frames_from_ffmpeg(a.source, a.fps, not a.stretch, a.speed, not a.mute, not a.no_aa)
            for fr in gen:
                sock.sendto(fr, addr)
            if not a.loop or a.test:
                break
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
