import pytest

from macrorss import __version__
from macrorss.cli import build_parser, main


def test_version_is_set():
    assert __version__


def test_parser_prog_name():
    assert build_parser().prog == "macrorss"


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_main_without_args_returns_zero():
    assert main([]) == 0
