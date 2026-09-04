__all__ = ['app']

import asyncio
import contextlib
import datetime
import io
import json
import os
import random
import subprocess
import traceback
from typing import TYPE_CHECKING, Annotated, override

import fastapi.responses
import hishel.fastapi
import pyreqwest.client
import pyreqwest.proxy
import zapros

from . import _downloader, _smiling

if TYPE_CHECKING:
    from typing import Any, type_check_only

    @type_check_only
    class _State(Any):
        downloading: asyncio.Queue[tuple[str, bool] | None]

    type _Request = fastapi.Request[_State]
else:
    type _Request = fastapi.Request


@contextlib.asynccontextmanager
async def _lifespan(_app: fastapi.FastAPI):
    parallel = 5
    proxy = pyreqwest.proxy.ProxyBuilder.https('http://localhost:1225/')
    builder = (
        pyreqwest.client.ClientBuilder()
            .default_cookie_store(enable=True)
            .https_only(enable=True)
            .max_connections(parallel)
            .proxy(proxy)
            .runtime_multithreaded(enable=True)
            .timeout(datetime.timedelta(seconds=60))
            .user_agent(_user_agent())
    )
    handler = _AsyncRetryMiddleware(zapros.AsyncPyreqwestHandler(builder))
    downloading: asyncio.Queue[tuple[str, bool] | None] = asyncio.Queue()
    downloaded: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
    async with contextlib.AsyncExitStack() as stack:
        if (
            (home := os.getenv('PIXI_PROJECT_ROOT'))
            and os.path.samefile(home, os.getcwd())
        ):
            os.makedirs('output', exist_ok=True)
            stack.enter_context(contextlib.chdir('output'))
        client = await stack.enter_async_context(zapros.AsyncClient(handler))
        tg = await stack.enter_async_context(asyncio.TaskGroup())
        for _ in range(parallel):
            tg.create_task(_worker(tg, client, downloading, downloaded))
        tg.create_task(_player(downloaded))
        try:
            yield {'downloading': downloading}
        finally:
            for _ in range(parallel):
                downloading.put_nowait(None)
            await downloading.join()
            downloaded.put_nowait(None)


app = fastapi.FastAPI(lifespan=_lifespan)


@app.get(
    '/{id_}',
    dependencies=[hishel.fastapi.cache(no_cache=True)],
    response_class=fastapi.responses.HTMLResponse,
)
async def submit(
    request: _Request,
    id_: Annotated[str, fastapi.Path(pattern=r'^(s[mos]|nm)\d+$')],
    best: bool = False,
):
    request.state.downloading.put_nowait((id_, best))
    return '<script>window.close();</script>'


class _AsyncRetryMiddleware(zapros.RetryMiddleware):
    @override
    async def ahandle(self, request: zapros.Request):
        response = await super().ahandle(request)
        response.raise_for_status()
        return response


def _message_box(id_: str, err: Exception):
    f = io.TextIOWrapper(io.BytesIO(), 'utf-16-le', 'backslashreplace')
    try:
        traceback.print_exception(err, file=f)
        f.flush()
        with f.detach() as g:
            g.write(b'\0')
            _smiling.message_box(id_, g.getvalue())
    finally:
        # https://github.com/python/cpython/issues/65562#issuecomment-1093653877
        try:
            f.close()
        except ValueError:
            pass


async def _player(downloaded: asyncio.Queue[tuple[str, str] | None]):
    while args := await downloaded.get():
        proc = await asyncio.create_subprocess_exec(
            'ffplay',
            '-hide_banner',
            '-loop', '0',
            '-window_title', *args,
            stdin=subprocess.DEVNULL,
        )
        await proc.wait()
        downloaded.task_done()
    downloaded.task_done()


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


async def _worker(
    tg: asyncio.TaskGroup,
    client: zapros.AsyncClient,
    downloading: asyncio.Queue[tuple[str, bool] | None],
    downloaded: asyncio.Queue[tuple[str, str] | None],
):
    while item := await downloading.get():
        id_, best = item
        try:
            path = await _downloader.download(id_, client, best=best)
        except Exception as e:
            tg.create_task(asyncio.to_thread(_message_box, id_, e))
        else:
            downloaded.put_nowait((id_, path))
        finally:
            downloading.task_done()
    downloading.task_done()
