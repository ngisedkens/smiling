__all__ = [
    'parse_html',
    'parse_m3u8',
]

from typing import Annotated, Literal, TypedDict

import bs4
import m3u8
import pydantic


def parse_html(markup: str):
    match bs4.BeautifulSoup(markup, 'html.parser').find(
        name='meta',
        attrs={'name': 'server-response', 'content': True},
    ):
        case bs4.Tag(attrs={'content': str(content)}):
            return _Content.model_validate_json(content).data.response["$watchV4"].data
        case _:
            raise LookupError()


def parse_m3u8(content: str):
    obj = m3u8.loads(content)
    return _M3U8.model_validate(obj.data)


class _Client(pydantic.BaseModel, extra='ignore'):
    watchTrackId: str


class _ContentMeta(pydantic.BaseModel):
    code: Literal['HTTP_200']
    status: Literal[200]


class _DomandItem(pydantic.BaseModel, extra='ignore'):
    id: str
    isAvailable: bool
    qualityLevel: pydantic.NonNegativeInt


class _Contents(pydantic.BaseModel, extra='ignore'):
    audios: list[_DomandItem]
    videos: list[_DomandItem]

    def outputs(self, *, best: bool = False):
        audio_src_id = (max if best else min)(
            [a for a in self.audios if a.isAvailable],
            key=lambda a: a.qualityLevel,
        ).id
        video_src_id = min(
            [v for v in self.videos if v.isAvailable],
            key=lambda v: v.qualityLevel,
        ).id
        return {'outputs': [[video_src_id, audio_src_id]]}


class _M3U8Header(pydantic.BaseModel):
    uri: str


class _M3U8Media(pydantic.BaseModel):
    default: Literal['YES']
    group_id: str
    name: Literal['Main Audio']
    type: Literal['AUDIO']
    uri: str


class _M3U8Segment(pydantic.BaseModel, extra='ignore'):
    uri: str


class _M3U8Key(pydantic.BaseModel):
    iv: Annotated[
        bytes,
        pydantic.BeforeValidator(lambda x: int(x, base=16).to_bytes(16)),
    ]
    method: Literal['AES-128']
    uri: str


class _M3U8(pydantic.BaseModel, extra='ignore'):
    keys: list[_M3U8Key]
    media: list[_M3U8Media]
    segment_map: list[_M3U8Header]
    segments: list[_M3U8Segment]
    targetduration: pydantic.PositiveInt | None = None
    version: Literal[6]


class _Media(pydantic.BaseModel, extra='ignore'):
    accessRightKey: str
    contents: _Contents | None = None


class _Permission(pydantic.BaseModel, extra='ignore'):
    isDeleted: Literal[False]


class _Video(pydantic.BaseModel, extra='ignore'):
    id: str
    permission: _Permission


class _Data(pydantic.BaseModel, extra='ignore'):
    client: _Client
    media: _Media
    video: _Video


class _WatchV4(pydantic.BaseModel, extra='ignore'):
    data: _Data


_Response = TypedDict("_Response", {"$watchV4": _WatchV4})


class _ContentData(pydantic.BaseModel, extra='ignore'):
    response: _Response


class _Content(pydantic.BaseModel):
    data: _ContentData
    meta: _ContentMeta
