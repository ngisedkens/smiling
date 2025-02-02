__all__ = ('download', 'prepare')

import asyncio
from collections.abc import Iterable
import json
import logging
import math
import mimetypes
import os
import random
import socket
import ssl
import subprocess
import time
from typing import Any
from typing import override
from typing import TYPE_CHECKING

import httpcore
import httpx
import pydantic
from urllib3.util import ssl_match_hostname
if TYPE_CHECKING:
    from urllib3.util.ssl_ import _TYPE_PEER_CERT_RET_DICT  # pyright: ignore[reportPrivateUsage]

from . import _main
from . import _parser
from ._types import Domand
from ._types import EventHooks
from ._types import Format
from ._types import HLS


async def download(id_: str, format_: Format, /) -> str:
    states = _main.states.get()
    prefix = '' if format_ == 'best' else '_'
    output_file = os.path.join(states['output_dir'], f'{prefix}{id_}.m4a')
    transport = httpx.AsyncHTTPTransport(retries=42)
    transport._pool._network_backend = states['network_backend']  # pyright: ignore[reportPrivateUsage]
    async with httpx.AsyncClient(
        event_hooks=states['event_hooks'],
        follow_redirects=True,
        headers={'User-Agent': _user_agent()},
        timeout=60,
        transport=transport,
    ) as client:
        response = await client.get(f'https://www.nicovideo.jp/watch/{id_}')
        try:
            root = _parser.parse_html(response.text)
            if dms := root.media.domand:
                assert root.video.id == id_
                response = await client.post(
                    f'https://nvapi.nicovideo.jp/v1/watch/{id_}/access-rights/hls',
                    json=_dms_json(dms, format_),
                    params={'actionTrackId': root.client.watchTrackId},
                    headers={
                        'X-Access-Right-Key': dms.accessRightKey,
                        'X-Frontend-Id': '6',
                        'X-Frontend-Version': '0',
                        'X-Request-With': 'https://www.nicovideo.jp',
                    },
                )
                hls = HLS.model_validate_json(response.text).data
                async with asyncio.timeout(
                    hls.expireTime.timestamp() - time.time(),
                ):
                    response = await client.get(hls.contentUrl)
                    url = _parser.parse_m3u8(response.text).media[0].uri
                    response = await client.get(url)
                    m3u8 = _parser.parse_m3u8(response.text)
                    if format_ == 'best':
                        stop = None
                    else:
                        assert m3u8.targetduration
                        stop = math.ceil(120 / m3u8.targetduration)
                    args = await asyncio.gather(
                        _m3u8_header(client, m3u8.segment_map[0].uri),
                        _m3u8_key(client, m3u8.keys[0].uri),
                        *[
                            _m3u8_segment(client, segment.uri)
                            for segment in m3u8.segments[:stop]
                        ],
                    )
                iv = m3u8.keys[0].iv.to_bytes(16)
                await _m3u8_concat(id_, output_file, iv, *args)
            else:
                raise NotImplementedError()
        except Exception as e:
            if not isinstance(e, httpx.HTTPStatusError):
                t = time.strftime('%Y%m%d%H%M%S')
                if content_type := response.headers.get('Content-Type'):
                    ext = mimetypes.guess_extension(content_type) or ''
                else:
                    ext = ''
                fullname = os.path.join(states['log_dir'], f'{id_}-{t}{ext}')
                with open(fullname, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                _logger.exception(
                    'Failed to download %s, see %s for details',
                    id_,
                    fullname,
                )
            raise
        return output_file


def prepare(hosts: dict[str, str], sni_hostname: dict[str, str]):
    async def event_hook(request: httpx.Request):
        url = request.url
        host = url.host
        if host in hosts:
            # https://www.python-httpx.org/advanced/extensions/#sni_hostname
            request.extensions['sni_hostname'] = sni_hostname.get(host, host)  # pyright: ignore[reportUnknownMemberType]
            request.headers['Host'] = host
        if _logger.isEnabledFor(logging.DEBUG):
            url = str(url)

            async def trace(event_name: str, _info: dict[str, Any], /):
                pair = (host, event_name)
                if pair not in seen:
                    seen.add(pair)
                    _logger.debug('%s: %s', event_name, url)

            request.extensions['trace'] = trace

    seen: set[tuple[str, str]] = set()
    event_hooks: EventHooks = {
        'request': [event_hook],
        'response': [_event_hook],
    }
    return event_hooks, _AsyncIOBackend(hosts)


class _AsyncIOBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, hosts: dict[str, str]):
        self._hosts = hosts

    @override
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ):
        host = self._hosts.get(host, host)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, local_addr=local_address),
            timeout,
        )
        if socket_options:
            sock: socket.socket = writer.get_extra_info('socket')
            for option in socket_options:
                if len(option) == 3:  # Bypass static type checking
                    sock.setsockopt(*option)
                else:
                    sock.setsockopt(*option)
        return _AsyncIOStream(reader, writer)

    @override
    def sleep(self, seconds: float):
        return asyncio.sleep(seconds)


class _AsyncIOStream(httpcore.AsyncNetworkStream):
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        self._reader = reader
        self._writer = writer

    @override
    def read(self, max_bytes: int, timeout: float | None = None):
        return asyncio.wait_for(self._reader.read(max_bytes), timeout)

    @override
    def write(self, buffer: bytes, timeout: float | None = None):
        self._writer.write(buffer)
        return asyncio.wait_for(self._writer.drain(), timeout)

    @override
    async def aclose(self):
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass

    @override
    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ):
        await self._writer.start_tls(
            ssl_context,
            server_hostname='',  # Bypass SNI RST
            ssl_handshake_timeout=timeout,
            ssl_shutdown_timeout=timeout,
        )
        peercert: _TYPE_PEER_CERT_RET_DICT | None = self._writer.get_extra_info(
            'peercert',
        )
        if server_hostname:
            ssl_match_hostname.match_hostname(peercert, server_hostname)
        return self

    @override
    def get_extra_info(self, info: str):
        return self._writer.get_extra_info(info)


def _dms_json(dms: Domand, format_: Format, /) -> pydantic.JsonValue:
    audio_src_id = (max if format_ == 'best' else min)(
        [a for a in dms.audios if a.isAvailable],
        key=lambda a: a.qualityLevel,
    ).id
    video_src_id = min(
        [a for a in dms.videos if a.isAvailable],
        key=lambda a: a.qualityLevel,
    ).id
    return {'outputs': [[video_src_id, audio_src_id]]}


async def _event_hook(response: httpx.Response):
    if not response.has_redirect_location:
        response.raise_for_status()


async def _m3u8_concat(
    id_: str,
    output_file: str,
    iv: bytes,
    header: bytes,
    key: bytes,
    *segments: bytes,
):
    states = _main.states.get()
    ffi = states['ffi']
    lib = states['lib']

    buf1 = bytearray(
        288  # sizeof(struct AVAES)
        + 16  # iv
    )
    buf1[288:] = iv
    n = len(header)
    buf2 = bytearray(sum(map(len, segments), n))
    buf2[:n] = header
    with (
        ffi.from_buffer('uint8_t[]', buf1, require_writable=True) as a,  # pyright: ignore[reportUnknownVariableType]
        ffi.from_buffer('uint8_t[]', buf2, require_writable=True) as b,  # pyright: ignore[reportUnknownVariableType]
    ):
        err = lib.av_aes_init(a, key, 128, 1)
        assert not err
        backup = bytes(buf1)
        iv_ = a + 288  # pyright: ignore[reportUnknownVariableType]
        for segment in segments:
            i = len(segment)
            buf2[n : n+i] = segment
            dst = src = b + n  # pyright: ignore[reportUnknownVariableType]
            lib.av_aes_crypt(a, dst, src, i//16, iv_, 1)
            buf1[:] = backup
            n += i - buf2[n+i-1]
    args = [
        'ffmpeg',
        '-hide_banner',
        '-i', '-',
        '-c', 'copy',
        '-metadata', f'comment={id_}',
        output_file,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(buf2[:n])
    if returncode := proc.returncode:
        raise subprocess.CalledProcessError(returncode, args, stdout, stderr)


async def _m3u8_header(client: httpx.AsyncClient, url: str):
    async with _main.states.get()['pool']:
        response = await client.get(url)
    return response.content


async def _m3u8_key(client: httpx.AsyncClient, url: str):
    response = await client.get(url)
    key = response.content
    if len(key) != 16:
        raise ValueError('Bad key size')
    return key


async def _m3u8_segment(client: httpx.AsyncClient, url: str):
    async with _main.states.get()['pool']:
        response = await client.get(url)
    segment = response.content
    if len(segment) % 16:
        raise ValueError('Bad segment size')
    return segment


def _user_agent():
    user_agent = {
        'Mozilla': '5.0 (Windows NT 10.0; Win64; x64)',
        'AppleWebKit': '537.36 (KHTML, like Gecko)',
        'Chrome': random.choice([
            '99.0.4844.84',
            '99.0.4844.82',
            '99.0.4844.74',
            '98.0.4758.102',
            '98.0.4758.82',
            '98.0.4758.80',
            '97.0.4692.99',
            '97.0.4692.71',
            '96.0.4664.110',
            '96.0.4664.93',
            '96.0.4664.45',
            '95.0.4638.69',
            '95.0.4638.54',
            '94.0.4606.81',
            '94.0.4606.71',
            '94.0.4606.61',
            '94.0.4606.54',
            '93.0.4577.82',
            '93.0.4577.63',
            '92.0.4515.159',
            '92.0.4515.131',
            '92.0.4515.107',
            '91.0.4472.164',
            '91.0.4472.124',
            '91.0.4472.114',
            '91.0.4472.106',
            '91.0.4472.101',
            '91.0.4472.77',
            '90.0.4430.212',
            '90.0.4430.93',
            '90.0.4430.72',
        ]),
        'Safari': '537.36',
    }
    return json.dumps(user_agent, separators=(' ', '/'))[1:-1].replace('"', '')


_logger = logging.getLogger(__package__)
