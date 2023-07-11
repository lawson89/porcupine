import logging
import pickle
import shutil
import sys
from pathlib import Path

import pytest

from porcupine import dirs
from porcupine.plugins import filetypes


@pytest.fixture
def custom_filetypes():
    # We don't overwrite the user's file because porcupine.dirs is monkeypatched
    if sys.platform == "win32":
        assert "Temp" in dirs.user_config_path.parts
    else:
        assert Path.home() not in dirs.user_config_path.parents

    (dirs.user_config_path / "filetypes.toml").write_text(
        """
["Mako template"]
filename_patterns = ["mako-templates/*.html"]
pygments_lexer = 'pygments.lexers.MakoHtmlLexer'

["C++".langserver]
command = "clangd"
language_id = "cpp"
settings = {clangd = {arguments = ["-std=c++17"]}}
"""
    )
    filetypes.filetypes.clear()
    filetypes.load_filetypes()

    yield
    (dirs.user_config_path / "filetypes.toml").unlink()
    filetypes.filetypes.clear()
    filetypes.load_filetypes()


def test_bad_filetype_on_command_line(run_porcupine):
    output = run_porcupine(["-n", "FooBar"], 2)
    assert "no filetype named 'FooBar'" in output


def test_unknown_filetype(filetab, tmp_path):
    # pygments does not know graphviz, see how it gets handled
    filetab.textwidget.insert(
        "end",
        """\
digraph G {
    Hello->World;
}
""",
    )
    filetab.path = tmp_path / "graphviz-hello-world.gvz"
    filetab.save()

    filetype = filetypes.get_filetype_for_tab(filetab)
    assert filetype["syntax_highlighter"] == "pygments"
    assert filetype["pygments_lexer"].endswith(".TextLexer")


def test_slash_in_filename_patterns(custom_filetypes, caplog, tmp_path):
    def lexer_name(path):
        return filetypes.guess_filetype_from_path(path)["pygments_lexer"]

    assert lexer_name(tmp_path / "foo" / "bar.html") == "pygments.lexers.HtmlLexer"
    assert lexer_name(tmp_path / "lol-mako-templates" / "bar.html") == "pygments.lexers.HtmlLexer"
    with caplog.at_level(logging.WARNING):
        assert (
            lexer_name(tmp_path / "mako-templates" / "bar.html") == "pygments.lexers.MakoHtmlLexer"
        )

    assert len(caplog.records) == 1
    assert "2 file types match" in caplog.records[0].message
    assert str(tmp_path) in caplog.records[0].message
    assert "HTML, Mako template" in caplog.records[0].message


@pytest.mark.skipif(shutil.which("clangd") is None, reason="example config uses clangd")
def test_cplusplus_toml_bug(tmp_path, tabmanager, custom_filetypes):
    (tmp_path / "foo.cpp").touch()
    tab = tabmanager.open_file(tmp_path / "foo.cpp")
    pickle.dumps(tab.get_state())  # should not raise an error


def test_settings_reset_when_filetype_changes(filetab, tmp_path):
    assert filetab.settings.get("filetype_name", object) == "Python"
    assert filetab.settings.get("comment_prefix", object) == "#"
    assert filetab.settings.get("langserver", object) is not None
    assert len(filetab.settings.get("example_commands", object)) >= 2

    filetab.save_as(tmp_path / "asdf.css")
    assert filetab.settings.get("filetype_name", object) is None
    assert filetab.settings.get("comment_prefix", object) is None
    assert filetab.settings.get("langserver", object) is None
    assert len(filetab.settings.get("example_commands", object)) == 0


def test_merging_settings():
    default = {
        "Plain Text": {"filename_patterns": ["*.txt"]},
        "Python": {
            "filename_patterns": ["*.py", "*.pyw"],
            "langserver": {
                "command": "{porcupine_python} -m pyls",
                "language_id": "python",
                "settings": {"pyls": {"plugins": {"jedi": {"environment": "{python_venv}"}}}},
            },
        },
    }
    user = {
        "Python": {
            "filename_patterns": ["*.foobar"],
            "langserver": {"settings": {"pyls": {"plugins": {"flake8": {"enabled": True}}}}},
        },
        "Custom File Type": {"filename_patterns": ["*.custom"]},
    }

    assert filetypes.merge_settings(default, user) == {
        "Plain Text": {"filename_patterns": ["*.txt"]},
        "Python": {
            "filename_patterns": ["*.foobar"],  # It is possible to get rid of patterns
            "langserver": {
                "command": "{porcupine_python} -m pyls",
                "language_id": "python",
                "settings": {
                    "pyls": {
                        "plugins": {
                            "jedi": {"environment": "{python_venv}"},
                            "flake8": {"enabled": True},
                        }
                    }
                },
            },
        },
        "Custom File Type": {"filename_patterns": ["*.custom"]},
    }
