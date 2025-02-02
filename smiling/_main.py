__all__ = ('cli_cmd', 'main', 'states')

import asyncio
import contextlib
import contextvars
import glob
import logging.handlers
import os
import pdb
import subprocess
import traceback
from typing import cast
from typing import override

import cffi

from . import _downloader
from . import _parser
from ._types import Format
from ._types import Lib
from ._types import Settings
from ._types import States

states: contextvars.ContextVar[States] = contextvars.ContextVar('states')


def cli_cmd(audio: str, format_: Format, /):
    id_ = _parser.parse_id(audio)
    try:
        asyncio.run(_cli_cmd(id_, format_))
    except:
        traceback.print_exc()
        pdb.post_mortem()


def main():
    asyncio.run(_main())


async def _cli_cmd(id_: str, format_: Format, /):
    async with _states(logging.DEBUG) as s:
        states.set(s)
        fullname = await _downloader.download(id_, format_)
        await _play(id_, fullname)


async def _main():
    async with _states(logging.INFO) as s:
        states.set(s)
        raise NotImplementedError()


async def _play(id_: str, fullname: str, /):
    proc = await asyncio.create_subprocess_exec(
        'ffplay',
        '-hide_banner',
        '-loop', '0',
        '-vcodec', 'h264_cuvid',
        '-window_title', id_,
        fullname,
        stdin=subprocess.DEVNULL,
    )
    await proc.wait()


class _RotatingFileHandler(logging.handlers.RotatingFileHandler):
    @override
    def _open(self):
        assert self.mode == 'a'
        return open(
            self.baseFilename,
            'a',
            encoding=self.encoding,
            errors=getattr(self, 'errors', None),
            newline='',
        )


@contextlib.asynccontextmanager
async def _states(level: int):
    log_dir = os.path.abspath(os.path.join(__file__, '../../log'))
    os.makedirs(log_dir, exist_ok=True)
    if level >= logging.INFO:
        handler = _RotatingFileHandler(
            os.path.join(log_dir, f'{__package__}.log'),
            maxBytes=20000 * 81,  # lines * chars
            backupCount=10,
            encoding='utf-8',
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            '[{asctime}] {levelname:8} {message}',
            datefmt='%Y-%m-%d %X',
            style='{',
        ),
    )
    logger = logging.getLogger(__package__)
    logger.addHandler(handler)
    logger.setLevel(level)

    output_dir = os.path.abspath(os.path.join(__file__, '../../output'))
    os.makedirs(output_dir, exist_ok=True)

    settings = Settings()
    event_hooks, network_backend = _downloader.prepare(
        settings.hosts,
        settings.sni_hostname,
    )

    [libpath] = glob.iglob(
        os.path.join(os.environ['CONDA_PREFIX'], r'Library\bin\avutil-*.dll'),
    )
    ffi = cffi.FFI()
    ffi.cdef(
        '''
        int av_aes_init(
            uint8_t *a,
            const uint8_t *key,
            int key_bits,
            int decrypt
        );

        void av_aes_crypt(
            uint8_t *a,
            uint8_t *dst,
            const uint8_t *src,
            int count,
            uint8_t *iv,
            int decrypt
        );
        ''',
    )
    lib = ffi.dlopen(libpath)
    try:
        yield States(
            event_hooks=event_hooks,
            ffi=ffi,
            lib=cast(Lib, lib),
            log_dir=log_dir,
            network_backend=network_backend,
            output_dir=output_dir,
            pool=asyncio.BoundedSemaphore(settings.parallel),
        )
    finally:
        ffi.dlclose(lib)
