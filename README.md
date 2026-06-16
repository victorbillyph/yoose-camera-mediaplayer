# Yoosee Camera Media Player

Stream audio to Yoosee (and generic Hisilicon) IP camera speakers via the RTSP backchannel protocol.

## How it works

These cameras use a non-standard RTSP extension (`USER_CMD_SET`) with `AudioCtlCmd:OPEN` to open a talkback channel. Once opened, raw PCM s16le audio is streamed over the same TCP connection using interleaved frames with Little Endian length encoding.

**No DESCRIBE/SETUP/PLAY needed** — the proprietary `USER_CMD_SET` replaces the entire RTSP handshake.

## CLI Usage

```bash
python3 talk.py --ip 192.168.2.2 --file audio.mp3
```

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `--ip` | `192.168.2.2` | Camera IP address |
| `--port` | `554` | RTSP port |
| `--file` | `~/Downloads/yt1s_nYWSz5R.mp3` | Audio file path |
| `--rate` | `16000` | Sample rate (Hz) |
| `--vol` | `0.8` | Volume (0.0–2.0) |
| `--debug` | — | Enable debug logging |

## Home Assistant Integration

### HACS (manual)

Copy `custom_components/yoosee_media_player/` into your HA `config/custom_components/` directory, restart Home Assistant, then add the integration via:

**Settings → Devices → Add Integration → Yoosee Camera Media Player**

### Manual install

```bash
cp -r custom_components/yoosee_media_player /path/to/homeassistant/config/custom_components/
```

### Configuration

Via the UI you need:
- **Host**: camera IP address
- **Port**: RTSP port (default 554)

### Services

| Service | Description |
|---------|-------------|
| `media_player.play_media` | Play audio (URL or local path) through camera speaker |
| `media_player.volume_set` | Set speaker volume (0–1) |

### TTS example

```yaml
service: media_player.play_media
target:
  entity_id: media_player.yoosee_speaker
data:
  media_content_id: "http://your-tts-server/tts.mp3"
  media_content_type: audio/mpeg
```

## Protocol details

1. Open TCP connection to `camera:554`
2. Send `USER_CMD_SET` with `Content-type: AudioCtlCmd:OPEN`
3. Camera responds `200 OK`
4. Stream PCM s16le frames (mono, 16000 Hz) with header:
   - `0x24` (magic byte)
   - `0x02` (channel 2)
   - Length **Little Endian** (332 = 12 padding + 320 audio)
   - 12 null bytes padding
   - 320 bytes raw PCM audio
5. Send `USER_CMD_SET AudioCtlCmd:CLOSE` to finish

## Files

| File | Purpose |
|------|---------|
| `talk.py` | Standalone CLI tool for streaming audio |
| `custom_components/yoosee_media_player/` | Home Assistant integration |
| `send_audio.py` | Original RTSP-based test script (deprecated) |

## Credits

Protocol reverse-engineered from [realldz/yoosee-intercom](https://github.com/realldz/yoosee-intercom).
