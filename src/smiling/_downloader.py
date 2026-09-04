__all__ = ['download']

import asyncio
import itertools
import math
import mimetypes
import subprocess
import time
from typing import Literal

import anyio
import pydantic
import zapros

from . import _parser, _smiling


async def download(
    id_: str,
    client: zapros.AsyncClient,
    *,
    best: bool = False,
):
    prefix = '' if best else '_'
    output_file = f'{prefix}{id_}.m4a'
    if not await anyio.Path(output_file).is_file():
        response = await client.get(f'https://www.nicovideo.jp/watch/{id_}')
        try:
            root = _parser.parse_html(response.text)
            if dms := root.media.domand:
                assert root.video.id == id_
                response = await client.post(
                    f'https://nvapi.nicovideo.jp/v1/watch/{id_}/access-rights/hls',
                    json=dms.outputs(best=best),
                    params={'actionTrackId': root.client.watchTrackId},
                    headers={
                        'X-Access-Right-Key': dms.accessRightKey,
                        'X-Frontend-Id': '6',
                        'X-Frontend-Version': '0',
                        'X-Request-With': 'https://www.nicovideo.jp',
                    },
                )
                hls = _HLS.model_validate_json(response.text).data
                async with asyncio.timeout(
                    hls.expireTime.timestamp() - time.time(),
                ):
                    response = await client.get(hls.contentUrl)
                    url = _parser.parse_m3u8(response.text).media[0].uri
                    response = await client.get(url)
                    m3u8 = _parser.parse_m3u8(response.text)
                    segments = m3u8.segments
                    if not best:
                        assert m3u8.targetduration
                        stop = math.ceil(120 / m3u8.targetduration)
                        segments = itertools.islice(segments, stop)
                    args = await asyncio.gather(
                        _get_content(client, m3u8.segment_map[0].uri),
                        _get_content(client, m3u8.keys[0].uri),
                        *[
                            _get_content(client, segment.uri)
                            for segment in segments
                        ],
                    )
                await _m3u8_concat(output_file, id_, m3u8.keys[0].iv, *args)
            else:
                raise NotImplementedError()
        except Exception as e:
            if not isinstance(e, zapros.StatusCodeError):
                t = time.strftime('%Y%m%d%H%M%S')
                if content_type := response.headers.get('Content-Type'):
                    ext = mimetypes.guess_extension(content_type) or ''
                else:
                    ext = ''
                log = anyio.Path(f'{id_}-{t}{ext}')
                await log.write_text(response.text, encoding='utf-8')
            raise
    return output_file


class _HLSData(pydantic.BaseModel):
    contentUrl: str
    createTime: pydantic.AwareDatetime
    expireTime: pydantic.AwareDatetime


class _HLSMeta(pydantic.BaseModel):
    status: Literal[201]


class _HLS(pydantic.BaseModel):
    data: _HLSData
    meta: _HLSMeta


async def _get_content(client: zapros.AsyncClient, url: str):
    return await (await client.get(url)).aread()


async def _m3u8_concat(
    output_file: str,
    comment: str,
    iv: bytes,
    header: bytes,
    key: bytes,
    *segments: bytes,
):
    assert len(key) == 16, 'Bad key size'
    data = _smiling.m3u8_concat(iv, header, key, segments)
    args = [
        'ffmpeg',
        '-hide_banner',
        '-i', '-',
        '-c', 'copy',
        '-metadata', f'comment={comment}',
        output_file,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert (stdin := proc.stdin)
    stdin.write(data)
    try:
        await stdin.drain()
    except OSError:
        pass
    stdin.close()
    if returncode := await proc.wait():
        raise subprocess.CalledProcessError(returncode, args)
