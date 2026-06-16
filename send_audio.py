#!/usr/bin/env python3
"""Send audio to Hisilicon/HIipCamera via RTSP interleaved (two-way audio)."""

import hashlib, socket, re, struct, time, math, sys, os

HOST = '192.168.2.2'
PORT = 554
USER = 'admin'
PASS = 'vic1011tor'
PATH = '/onvif1'

def md5(s):
    return hashlib.md5(s.encode()).hexdigest()

def make_auth(method, uri, nonce, realm):
    ha1 = md5(f'{USER}:{realm}:{PASS}')
    ha2 = md5(f'{method}:{uri}')
    response = md5(f'{ha1}:{nonce}:{ha2}')
    return f'Digest username="{USER}", realm="{realm}", nonce="{nonce}", uri="{uri}", algorithm=MD5, response="{response}"'

def linear_to_alaw(sample):
    sample = max(-32768, min(32767, sample))
    sign = (sample >> 8) & 0x80
    if sample < 0:
        sample = -sample
    if sample > 0x7FFF:
        sample = 0x7FFF
    if sample >= 256:
        exponent = int(math.log2(sample >> 4)) + 1
        mantissa = (sample >> (exponent + 4)) & 0x0F
        alaw = (sign | (exponent << 4) | mantissa) ^ 0xD5
    else:
        alaw = (sign | (sample >> 4)) ^ 0xD5 if sample >= 16 else (sign | sample) ^ 0xD5
    return alaw & 0xFF

def make_rtp(seq, ts, ssrc=0x12345678, pt=8, marker=0):
    first = (2 << 6) | (0 << 5) | (0 << 4) | 0
    second = (marker << 7) | pt
    return struct.pack('!BBHII', first, second, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)

def recv_response(sock):
    data = b''
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        data += chunk
        if data.endswith(b'\r\n\r\n'):
            m = re.search(rb'Content-Length: (\d+)\r\n', data)
            if m:
                clen = int(m.group(1))
                while len(data) - data.find(b'\r\n\r\n') - 4 < clen:
                    data += sock.recv(min(clen, 4096))
            break
    return data.decode('utf-8', errors='replace')

def generate_tone(freq=440, duration=2, sample_rate=16000):
    samples = int(sample_rate * duration)
    for i in range(samples):
        val = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        yield linear_to_alaw(val)

def pcm16_to_alaw(pcm16_bytes):
    for i in range(0, len(pcm16_bytes), 2):
        sample = int.from_bytes(pcm16_bytes[i:i+2], 'little', signed=True)
        yield linear_to_alaw(sample)

def send_audio(audio_samples, sample_rate=16000, block_size=320):
    s = socket.socket()
    s.settimeout(10)
    s.connect((HOST, PORT))
    uri = f'rtsp://{HOST}:{PORT}{PATH}'

    s.send(f'OPTIONS {uri} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    recv_response(s)

    s.send(f'DESCRIBE {uri} RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    resp = recv_response(s)
    m = re.search(r'nonce="([^"]+)"', resp)
    if not m:
        print('Failed to get nonce')
        s.close()
        return False
    nonce = m.group(1)
    realm = 'HIipCamera'

    auth = make_auth('DESCRIBE', uri, nonce, realm)
    s.send(f'DESCRIBE {uri} RTSP/1.0\r\nCSeq: 3\r\nAuthorization: {auth}\r\nAccept: application/sdp\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    recv_response(s)
    print('DESCRIBE OK')

    auth = make_auth('SETUP', f'{uri}/track2', nonce, realm)
    s.send(f'SETUP {uri}/track2 RTSP/1.0\r\nCSeq: 4\r\nAuthorization: {auth}\r\nTransport: RTP/AVP/TCP;interleaved=2-3\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    resp = recv_response(s)
    m = re.search(r'Session: (\d+)', resp)
    session = m.group(1) if m else '0'
    print(f'SETUP track2 OK, Session: {session}')

    auth = make_auth('PLAY', uri, nonce, realm)
    s.send(f'PLAY {uri} RTSP/1.0\r\nCSeq: 5\r\nAuthorization: {auth}\r\nSession: {session}\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    recv_response(s)
    print('PLAY OK')

    time.sleep(0.3)
    s.setblocking(False)

    ssrc = 0x12345678
    seq = 0
    ts = 0
    buf = []
    sent = 0

    for alaw_sample in audio_samples:
        buf.append(alaw_sample)
        if len(buf) >= block_size:
            try:
                while True:
                    s.recv(65536)
            except:
                pass

            payload = bytes(buf[:block_size])
            buf = buf[block_size:]
            rtp = make_rtp(seq, ts, ssrc, pt=8)
            frame = b'\x24\x02' + struct.pack('!H', len(rtp + payload)) + rtp + payload
            s.send(frame)
            ts += block_size
            seq += 1
            sent += 1
            time.sleep(block_size / sample_rate * 0.5)

    if buf:
        try:
            while True:
                s.recv(65536)
        except:
            pass
        payload = bytes(buf)
        rtp = make_rtp(seq, ts, ssrc, pt=8)
        frame = b'\x24\x02' + struct.pack('!H', len(rtp + payload)) + rtp + payload
        s.send(frame)

    s.setblocking(True)
    s.settimeout(5)
    auth = make_auth('TEARDOWN', uri, nonce, realm)
    s.send(f'TEARDOWN {uri} RTSP/1.0\r\nCSeq: 6\r\nAuthorization: {auth}\r\nSession: {session}\r\nUser-Agent: Lavf\r\n\r\n'.encode())
    recv_response(s)
    s.close()
    print(f'Sent {sent} audio packets, TEARDOWN OK')
    return True

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--tone':
        freq = float(sys.argv[2]) if len(sys.argv) > 2 else 440
        dur = float(sys.argv[3]) if len(sys.argv) > 3 else 2
        print(f'Sending {freq}Hz tone for {dur}s...')
        send_audio(generate_tone(freq, dur))
    elif len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        import wave
        with wave.open(sys.argv[1], 'rb') as wav:
            if wav.getnchannels() != 1:
                print('Only mono WAV supported')
                sys.exit(1)
            if wav.getsampwidth() != 2:
                print('Only 16-bit WAV supported')
                sys.exit(1)
            print(f'Sending {sys.argv[1]} ({wav.getnframes()//wav.getframerate()}s)...')
            send_audio(pcm16_to_alaw(wav.readframes(wav.getnframes())), wav.getframerate())
    else:
        print('Usage:')
        print(f'  {sys.argv[0]} --tone [freq=440] [dur=2]')
        print(f'  {sys.argv[0]} arquivo.wav')
