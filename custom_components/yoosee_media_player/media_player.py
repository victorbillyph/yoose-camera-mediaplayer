import logging
import mimetypes
import os
import tempfile
from typing import Optional

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEFAULT_RATE, DEFAULT_VOLUME
from .talk import play_audio, set_volume

_LOGGER = logging.getLogger(__name__)

SUPPORT_YOOSEE = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.TURN_OFF
)


async def async_setup_entry(hass, entry, async_add_entities):
    data = entry.data
    async_add_entities(
        [
            YooseeMediaPlayer(
                name=data.get(CONF_NAME, "Yoosee Speaker"),
                host=data[CONF_HOST],
                port=data.get(CONF_PORT, 554),
            )
        ]
    )


class YooseeMediaPlayer(MediaPlayerEntity):
    _attr_should_poll = False

    def __init__(self, name, host, port=554):
        self._attr_name = name
        self._attr_unique_id = f"yoosee_media_player_{host}"
        self._host = host
        self._port = port
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = 0.8
        self._attr_supported_features = SUPPORT_YOOSEE
        self._attr_media_title = None
        self._playing = False
        self._stop_requested = False

    async def async_play_media(self, media_type, media_id, **kwargs):
        self._stop_requested = False
        title = media_id.rsplit("/", 1)[-1] if "/" in media_id else media_id
        self._attr_media_title = title
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

        def progress(bytes_sent):
            if self._stop_requested:
                raise InterruptedError("Stopped")

        try:
            url = media_id
            if not url.startswith(("http://", "https://")):
                try:
                    from homeassistant.components.media_source import (
                        async_resolve_media,
                    )
                    resolved = await async_resolve_media(self.hass, media_id)
                    if resolved:
                        url = resolved.url
                except (ImportError, ValueError):
                    if not os.path.isfile(media_id):
                        _LOGGER.error("Media not found: %s", media_id)
                        self._attr_state = MediaPlayerState.IDLE
                        self.async_write_ha_state()
                        return

            if url.startswith(("http://", "https://")):
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            _LOGGER.error("Failed to download %s: %s", url, resp.status)
                            self._attr_state = MediaPlayerState.IDLE
                            self.async_write_ha_state()
                            return
                        data = await resp.read()
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                tmp.write(data)
                tmp.close()
                audio_path = tmp.name
            else:
                audio_path = media_id

            await self.hass.async_add_executor_job(
                play_audio,
                self._host,
                self._port,
                audio_path,
                DEFAULT_RATE,
                self._attr_volume_level,
                progress,
            )

            if url != audio_path:
                os.unlink(audio_path)
        except InterruptedError:
            _LOGGER.debug("Playback stopped by user")
        except Exception as e:
            _LOGGER.error("Playback error: %s", e)

        self._attr_state = MediaPlayerState.IDLE
        self._attr_media_title = None
        self.async_write_ha_state()

    async def async_browse_media(
        self, media_content_type: Optional[str] = None,
        media_content_id: Optional[str] = None,
    ) -> BrowseMedia:
        if media_content_id:
            return BrowseMedia(
                media_class="directory",
                media_content_id=media_content_id,
                media_content_type="",
                title=media_content_id.rsplit("/", 1)[-1],
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        media_class="music",
                        media_content_id=os.path.join(media_content_id, f),
                        media_content_type=mimetypes.guess_type(f)[0] or "audio/mpeg",
                        title=f,
                        can_play=True,
                        can_expand=False,
                        thumbnail=None,
                    )
                    for f in sorted(os.listdir(media_content_id))
                    if f.endswith((".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"))
                ],
            )

        media_dirs = []
        for p in ["/media", "/config/media"]:
            if os.path.isdir(p):
                media_dirs.append(p)

        return BrowseMedia(
            media_class="directory",
            media_content_id="",
            media_content_type="",
            title="Yoosee Media Player",
            can_play=False,
            can_expand=True,
            children=[
                BrowseMedia(
                    media_class="directory",
                    media_content_id=d,
                    media_content_type="",
                    title=os.path.basename(d) or d,
                    can_play=False,
                    can_expand=True,
                    thumbnail=None,
                )
                for d in media_dirs
            ],
        )

    async def async_stop(self):
        self._stop_requested = True
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_turn_off(self):
        await self.async_stop()

    async def async_set_volume_level(self, volume):
        self._attr_volume_level = volume
        await self.hass.async_add_executor_job(
            set_volume, self._host, self._port, int(volume * 100)
        )
        self.async_write_ha_state()

    async def async_volume_up(self):
        new_vol = min(1.0, self._attr_volume_level + 0.1)
        await self.async_set_volume_level(new_vol)

    async def async_volume_down(self):
        new_vol = max(0.0, self._attr_volume_level - 0.1)
        await self.async_set_volume_level(new_vol)
