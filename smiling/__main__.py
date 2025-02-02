import sys

from . import _cli
from . import _main


def main():
    if len(sys.argv) <= 1:
        _main.main()
    else:
        _cli.main()


if __name__ == '__main__':
    main()
