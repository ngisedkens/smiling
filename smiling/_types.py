__all__ = [
    'Content',
    'Domand',
    'EventHooks',
    'Format',
    'HLS',
    'Lib',
    'M3U8',
    'Settings',
    'States',
]

import asyncio
from collections.abc import Callable
from collections.abc import Coroutine
from typing import Annotated
from typing import Any
from typing import Literal
from typing import override
from typing import Protocol
from typing import TypedDict

from annotated_types import Le
import cffi
import httpcore
import httpx
import pydantic
import pydantic_settings

assert __package__

type _EventHooks[T] = list[Callable[[T], Coroutine[Any, Any, object]]]
EventHooks = dict[str, _EventHooks[httpx.Request] | _EventHooks[httpx.Response]]
Format = Literal['best', 'worst']


class _Client(pydantic.BaseModel):
    watchTrackId: str

    model_config = pydantic.ConfigDict(extra='ignore')


class _ContentMeta(pydantic.BaseModel):
    code: Literal['HTTP_200']
    status: Literal[200]


class _DomandItem(pydantic.BaseModel):
    id: str
    isAvailable: bool
    qualityLevel: pydantic.NonNegativeInt

    model_config = pydantic.ConfigDict(extra='ignore')


class Domand(pydantic.BaseModel):
    accessRightKey: str
    audios: list[_DomandItem]
    videos: list[_DomandItem]

    model_config = pydantic.ConfigDict(extra='ignore')


class _HLSData(pydantic.BaseModel):
    contentUrl: str
    createTime: pydantic.AwareDatetime
    expireTime: pydantic.AwareDatetime


class _HLSMeta(pydantic.BaseModel):
    status: Literal[201]


class HLS(pydantic.BaseModel):
    data: _HLSData
    meta: _HLSMeta


class Lib(Protocol):
    def av_aes_init(
        self,
        a: Any,
        key: Any,
        key_bits: Literal[128],
        decrypt: Literal[1],
    ) -> int: ...

    def av_aes_crypt(
        self,
        a: Any,
        dst: Any,
        src: Any,
        count: int,
        iv: Any,
        decrypt: Literal[1],
    ) -> None: ...


class _M3U8Header(pydantic.BaseModel):
    uri: str


class _M3U8Media(pydantic.BaseModel):
    default: Literal['YES']
    group_id: str
    name: Literal['Main Audio']
    type: Literal['AUDIO']
    uri: str


class _M3U8Segment(pydantic.BaseModel):
    uri: str

    model_config = pydantic.ConfigDict(extra='ignore')


class _M3U8Key(pydantic.BaseModel):
    iv: Annotated[
        pydantic.NonNegativeInt,
        pydantic.BeforeValidator(lambda x: int(x, base=16)),
        Le(0xffffffff_ffffffff_ffffffff_ffffffff),
    ]
    method: Literal['AES-128']
    uri: str


class M3U8(pydantic.BaseModel):
    keys: list[_M3U8Key]
    media: list[_M3U8Media]
    segment_map: list[_M3U8Header]
    segments: list[_M3U8Segment]
    targetduration: pydantic.PositiveInt | None = None
    version: Literal[6]

    model_config = pydantic.ConfigDict(extra='ignore')


class _PaymentVideo(pydantic.BaseModel):
    isAdmission: Literal[False]
    isPremium: Literal[False]
    isPpv: Literal[False]

    model_config = pydantic.ConfigDict(extra='ignore')


class _Payment(pydantic.BaseModel):
    video: _PaymentVideo

    model_config = pydantic.ConfigDict(extra='ignore')


class _Video(pydantic.BaseModel):
    id: str
    isDeleted: Literal[False]

    model_config = pydantic.ConfigDict(extra='ignore')


class _Media(pydantic.BaseModel):
    domand: Domand | None = None

    model_config = pydantic.ConfigDict(extra='ignore')


class _Response(pydantic.BaseModel):
    client: _Client
    media: _Media
    payment: _Payment
    video: _Video

    model_config = pydantic.ConfigDict(extra='ignore')


class _ContentData(pydantic.BaseModel):
    response: _Response

    model_config = pydantic.ConfigDict(extra='ignore')


class Content(pydantic.BaseModel):
    data: _ContentData
    meta: _ContentMeta


class Settings(pydantic_settings.BaseSettings):
    hosts: dict[str, str] = {}
    parallel: pydantic.PositiveInt = 5
    sni_hostname: dict[str, str] = {}

    model_config = pydantic_settings.SettingsConfigDict(
        pyproject_toml_table_header=('tool', __package__),
    )

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ):
        return (
            pydantic_settings.PyprojectTomlConfigSettingsSource(settings_cls),
        )


class States(TypedDict):
    event_hooks: EventHooks
    ffi: cffi.FFI
    lib: Lib
    log_dir: str
    network_backend: httpcore.AsyncNetworkBackend
    output_dir: str
    pool: asyncio.BoundedSemaphore
