import logging
import os

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
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
        self._stop_requested = False

    async def async_play_media(self, media_type, media_id, **kwargs):
        self._stop_requested = False
        self._attr_media_title = media_id.rsplit("/", 1)[-1] if "/" in media_id else media_id
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

        def progress(bytes_sent):
            if self._stop_requested:
                raise InterruptedError("Stopped")

        try:
            if media_source.is_media_source_id(media_id):
                resolved = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id
                )
                media_id = async_process_play_media_url(self.hass, resolved.url)

            if not media_id.startswith(("http://", "https://", "/")) and not os.path.isfile(media_id):
                _LOGGER.error("Media not accessible: %s", media_id)
                self._attr_state = MediaPlayerState.IDLE
                self.async_write_ha_state()
                return

            await self.hass.async_add_executor_job(
                play_audio,
                self._host,
                self._port,
                media_id,
                DEFAULT_RATE,
                self._attr_volume_level,
                progress,
            )
        except InterruptedError:
            _LOGGER.debug("Playback stopped by user")
        except Exception as e:
            _LOGGER.error("Playback error: %s", e)

        self._attr_state = MediaPlayerState.IDLE
        self._attr_media_title = None
        self.async_write_ha_state()

    async def async_browse_media(
        self, media_content_type=None, media_content_id=None
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
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
