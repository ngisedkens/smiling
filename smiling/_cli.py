__all__ = ('main',)

from typing import Annotated

import pydantic
import pydantic_settings
import rich_argparse

from . import _main
from . import _parser
from ._types import Format


def main():
    pydantic_settings.CliApp.run(
        _Main,
        cli_settings_source=pydantic_settings.CliSettingsSource(
            _Main,
            formatter_class=rich_argparse.RawDescriptionRichHelpFormatter,
        ),
    )


class _Main(pydantic_settings.BaseSettings):
    """Download audio and play it.

    If invoked without any command-line arguments, launch a server instead.
    """

    audio: Annotated[
        pydantic_settings.CliPositionalArg[str],
        pydantic.Field(
            description='URL or sm-number of the audio to download',
            min_length=3,
            pattern=_parser.pattern,
        ),
    ]
    format_: Annotated[
        Format,
        pydantic.Field(alias='f', description='Audio format'),
    ] = 'worst'

    model_config = pydantic_settings.SettingsConfigDict(
        nested_model_default_partial_update=True,
        case_sensitive=True,
        cli_hide_none_type=True,
        cli_avoid_json=True,
        cli_enforce_required=True,
        cli_implicit_flags=True,
        cli_prog_name=__package__,
    )

    def cli_cmd(self):
        _main.cli_cmd(self.audio, self.format_)


if __name__ == '__main__':
    main()
