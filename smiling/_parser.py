__all__ = [
    'parse_html',
    'parse_id',
    'parse_m3u8',
    'pattern',
]

import re

import bs4
import m3u8

from ._types import Content
from ._types import M3U8

pattern = re.compile(r'\b((?:sm|nm|so)\d+)\b')


def parse_html(markup: str):
    match bs4.BeautifulSoup(markup, 'html.parser').find(
        name='meta',
        attrs={'name': 'server-response', 'content': True},
    ):
        case bs4.Tag(attrs={'content': str(content)}):
            return Content.model_validate_json(content).data.response
        case _:
            raise LookupError()


def parse_id(input_: str):
    match pattern.findall(input_):
        case [str(id_)]:
            return id_
        case []:
            raise ValueError(f'No video ID found in {input_!r}')
        case all_:
            raise ValueError(f'Multiple video IDs found: {all_}')


def parse_m3u8(content: str):
    obj = m3u8.loads(content)
    return M3U8.model_validate(obj.data)
