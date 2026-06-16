import socket
import struct
import subprocess
import time
import collections

CHUNK_SIZE = 320
FRAME_LEN = 332
MAX_BUFFER_AHEAD_MS = 2000
SPEED_MULTIPLIER = 1.0


def open_talk(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((host, port))
    cmd = (
        f"USER_CMD_SET rtsp://{host}/onvif0 RTSP/1.0\r\n"
        "CSeq: 8\r\n"
        "Content-length: strlen(Content-type)\r\n"
        "Content-type: AudioCtlCmd:OPEN\r\n\r\n"
    )
    s.sendall(cmd.encode())
    resp = b""
    while True:
        c = s.recv(1)
        if not c:
            break
        resp += c
        if b"\r\n\r\n" in resp:
            break
    if b"200" not in resp:
        s.close()
        raise ConnectionError(f"OPEN failed: {resp.decode(errors='ignore')}")
    s.settimeout(None)
    return s


def close_talk(sock, host):
    cmd = (
        f"USER_CMD_SET rtsp://{host}/onvif0 RTSP/1.0\r\n"
        "CSeq: 10\r\n"
        "Content-length: strlen(Content-type)\r\n"
        "Content-type: AudioCtlCmd:CLOSE\r\n\r\n"
    )
    try:
        sock.sendall(cmd.encode())
    except OSError:
        pass


def send_frame(sock, data):
    header = struct.pack("<BBH", 0x24, 0x02, FRAME_LEN)
    sock.sendall(header + b"\x00" * 12 + data)


def set_volume(host, port, volume, timeout=5):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        body = f"volume: {int(volume)}\r\n".encode()
        req = (
            f"SET_PARAMETER rtsp://{host}/onvif1 RTSP/1.0\r\n"
            "CSeq: 3\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Content-Type: text/parameters\r\n\r\n"
        ).encode() + body
        s.sendall(req)
        s.recv(1024)
        s.close()
        return True
    except OSError:
        return False


def stream_audio(sock, audio_path, rate=16000, volume=0.8, on_progress=None):
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            audio_path,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(rate),
            "-ac",
            "1",
            "-filter:a",
            f"volume={volume}",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    queue = collections.deque()
    total_sent = 0
    start_time = 0
    running = True

    def feeder():
        nonlocal queue
        while running:
            chunk = ffmpeg.stdout.read(CHUNK_SIZE)
            if not chunk:
                break
            if len(chunk) < CHUNK_SIZE:
                chunk += b"\x00" * (CHUNK_SIZE - len(chunk))
            queue.append(chunk)

    import threading
    t = threading.Thread(target=feeder, daemon=True)
    t.start()

    while running:
        if not queue:
            if ffmpeg.poll() is not None:
                break
            time.sleep(0.01)
            continue

        if start_time == 0:
            burst = (rate * 2) // CHUNK_SIZE
            if len(queue) >= burst:
                for _ in range(burst):
                    send_frame(sock, queue.popleft())
                    total_sent += CHUNK_SIZE
                start_time = time.time() * 1000
                if on_progress:
                    on_progress(total_sent)
            else:
                time.sleep(0.05)
                continue

        elapsed = (time.time() * 1000) - start_time
        audio_ms = ((total_sent / (rate * 2)) * 1000) / SPEED_MULTIPLIER

        if audio_ms > elapsed + MAX_BUFFER_AHEAD_MS:
            time.sleep(0.01)
            continue

        send_frame(sock, queue.popleft())
        total_sent += CHUNK_SIZE
        if on_progress:
            on_progress(total_sent)

    ffmpeg.wait()
    return total_sent


def play_audio(host, port, audio_path, rate=16000, volume=0.8, on_progress=None):
    sock = open_talk(host, port)
    try:
        bytes_sent = stream_audio(sock, audio_path, rate, volume, on_progress)
        return bytes_sent
    finally:
        close_talk(sock, host)
        sock.close()
