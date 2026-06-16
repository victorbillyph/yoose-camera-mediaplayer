import argparse, collections, socket, struct, subprocess, sys, threading, time

CHUNK_SIZE = 320
FRAME_LEN = 332
MAX_BUFFER_AHEAD_MS = 2000
SPEED_MULTIPLIER = 1.0

def send_audio(ip, port, audio_file, rate=8000, volume=0.5, debug=False):
    path = '/onvif0'
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((ip, port))

    cmd = (
        f"USER_CMD_SET rtsp://{ip}{path} RTSP/1.0\r\n"
        "CSeq: 8\r\n"
        "Content-length: strlen(Content-type)\r\n"
        "Content-type: AudioCtlCmd:OPEN\r\n\r\n"
    )
    sock.sendall(cmd.encode())

    resp = b''
    while True:
        c = sock.recv(1)
        if not c: break
        resp += c
        if b'\r\n\r\n' in resp: break

    if b'200' not in resp:
        print(f'OPEN failed: {resp.decode(errors="ignore")}')
        sock.close()
        return False

    print('Camera ready.')
    sock.settimeout(None)

    ffmpeg = subprocess.Popen([
        'ffmpeg', '-v', 'error', '-i', audio_file,
        '-f', 's16le', '-acodec', 'pcm_s16le',
        '-ar', str(rate), '-ac', '1',
        '-filter:a', f'volume={volume}', 'pipe:1'
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    audio_queue = collections.deque()
    total_sent = 0
    start_time = 0
    running = True
    last_send = [0.0]

    def send_frame(data):
        nonlocal total_sent
        try:
            header = struct.pack('<BBH', 0x24, 0x02, FRAME_LEN)
            sock.sendall(header + b'\x00' * 12 + data)
            total_sent += len(data)
            last_send[0] = time.time()
        except Exception as e:
            print(f'Send error: {e}')

    def feeder():
        nonlocal audio_queue
        while running:
            chunk = ffmpeg.stdout.read(CHUNK_SIZE)
            if not chunk:
                break
            if len(chunk) < CHUNK_SIZE:
                chunk += b'\x00' * (CHUNK_SIZE - len(chunk))
            audio_queue.append(chunk)

    threading.Thread(target=feeder, daemon=True).start()

    while running:
        if not audio_queue:
            if ffmpeg.poll() is not None:
                break
            time.sleep(0.01)
            continue

        if start_time == 0:
            burst = int((rate * 2) / CHUNK_SIZE)
            if len(audio_queue) >= burst:
                if debug:
                    print(f'Bursting {burst} packets...')
                for _ in range(burst):
                    send_frame(audio_queue.popleft())
                start_time = time.time() * 1000
            else:
                time.sleep(0.05)
                continue

        elapsed = (time.time() * 1000) - start_time
        audio_ms = ((total_sent / (rate * 2)) * 1000) / SPEED_MULTIPLIER

        if audio_ms > elapsed + MAX_BUFFER_AHEAD_MS:
            time.sleep(0.01)
            continue

        send_frame(audio_queue.popleft())

    ffmpeg.wait()

    close = (
        f"USER_CMD_SET rtsp://{ip}{path} RTSP/1.0\r\n"
        "CSeq: 10\r\n"
        "Content-length: strlen(Content-type)\r\n"
        "Content-type: AudioCtlCmd:CLOSE\r\n\r\n"
    )
    sock.sendall(close.encode())
    time.sleep(0.1)
    sock.close()
    print(f'Done. Sent {total_sent} bytes.')
    return True

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Two-way audio for Yoosee IP cameras')
    p.add_argument('--ip', default='192.168.2.2', help='Camera IP')
    p.add_argument('--port', type=int, default=554, help='RTSP port')
    p.add_argument('--file', default='/home/victor/Downloads/yt1s_nYWSz5R.mp3', help='Audio file')
    p.add_argument('--rate', type=int, default=16000, help='Sample rate (default 16000)')
    p.add_argument('--vol', type=float, default=0.8, help='Volume 0.0-2.0')
    p.add_argument('--debug', action='store_true', help='Debug output')
    args = p.parse_args()
    send_audio(args.ip, args.port, args.file, args.rate, args.vol, args.debug)
