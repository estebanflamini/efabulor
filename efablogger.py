# EFABULOR: a user-friendly command-line front-end to espeak
# Copyright (C) 2021-2024 Esteban Flamini <http://estebanflamini.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


###############################################################################
# Import global packages and initialize global CONSTANTS
from efabglobals import *


from efabargs import get_args


# A provisory replacement for efabrto.RuntimeOptions
@dataclass
class _Options:
    window_width_adjustment: int = 0
    left_intent: int = 0
    right_indent: int = 0
    no_info: bool = False


_options = _Options()


def register_options(options):
    global _options
    _options = options


DEFAULT_WINDOW_WIDTH = 72

NORMAL = 1
NORMAL_EXTENDED = 2
INFO = 3
INFO_EXTENDED = 4
ERROR = 5
ERROR_EXTENDED = 6
INTERACTION = 7
PAUSE = 8

_target = {
    NORMAL: sys.stdout,
    NORMAL_EXTENDED: sys.stdout,
    INFO: sys.stdout,
    INFO_EXTENDED: sys.stdout,
    ERROR: sys.stderr,
    ERROR_EXTENDED: sys.stderr,
    INTERACTION: sys.stdout,
    PAUSE: sys.stdout,
}

_prompt = {
    NORMAL: "",
    NORMAL_EXTENDED: ">>> ",
    INFO: "> ",
    INFO_EXTENDED: "> ",
    ERROR: "[!] ",
    ERROR_EXTENDED: "[!] ",
    INTERACTION: "> ",
    PAUSE: "> ",
}

_prompt_scripted = {
    NORMAL: "[Normal] ",
    NORMAL_EXTENDED: "[NormalEx]  ",
    INFO: "[Info] ",
    INFO_EXTENDED: "[InfoEx] ",
    ERROR: "[Error] ",
    ERROR_EXTENDED: "[ErrorEx] ",
    INTERACTION: "[Prompt] ",
    PAUSE: "[Pause] ",
}


@dataclass
class _State:
    _first_time: bool = True
    _counter: int = 0


_state = _State()


lock = threading.RLock()


def window_width(target=sys.stdout):
    try:
        return (
            os.get_terminal_size(target.fileno()).columns
            - _options.window_width_adjustment
        )
    except OSError:
        return DEFAULT_WINDOW_WIDTH - _options.window_width_adjustment


def say(
    what, type_of_msg, wrap=True,
    print_prompt=True, end="\n\n", mandatory=False
):

    scripted_mode = get_args().scripted

    if not isinstance(what, str):
        what = str(what)

    with lock:

        if _options.no_info and type_of_msg == INFO and not mandatory:
            return False

        target = _target[type_of_msg]

        if _state._first_time:
            _state._first_time = False
            print(file=target)

        what = what.strip()

        prompt = _prompt_scripted if scripted_mode else _prompt

        width = window_width(target)

        if type_of_msg == ERROR_EXTENDED:
            what = textwrap.indent(what, prompt[type_of_msg], lambda x: True)
        elif type_of_msg == INTERACTION and scripted_mode:
            what = textwrap.indent(what, prompt[type_of_msg], lambda x: True)
        elif type_of_msg in [NORMAL_EXTENDED, INFO_EXTENDED]:
            width -= len(prompt[type_of_msg])
            what = "\n".join(
                textwrap.fill(
                    x, width, break_on_hyphens=False,
                    replace_whitespace=False
                )
                for x in what.split("\n")
            )
            what = textwrap.indent(what, prompt[type_of_msg], lambda x: True)
        else:
            if print_prompt:
                what = prompt[type_of_msg] + what
            if type_of_msg == NORMAL:
                width -= (_options.left_indent + _options.right_indent)
            if wrap:
                what = "\n".join(
                    textwrap.fill(
                        x, width, break_on_hyphens=False,
                        replace_whitespace=False
                    )
                    for x in what.split("\n")
                )
            if type_of_msg == NORMAL:
                what = textwrap.indent(what, " " * _options.left_indent)
        print(what, file=target, end=end)
        target.flush()
        _state._counter += 1
        return True


def separate(type_of_msg):
    with lock:
        print(file=_target[type_of_msg])


def get_file(type_of_msg):
    return _target[type_of_msg]


def get_prompt(type_of_msg):
    return _prompt[type_of_msg]


def get_counter():
    with lock:
        return _state._counter


def report_error(e, type_of_msg=None):
    with lock:
        if isinstance(e, subprocess.CalledProcessError):
            say(
                _(
                    "An error has occurred while executing an external "
                    "command %s."
                ) % e.cmd,
                type_of_msg=ERROR,
            )
            say(_("The process error output is:"), type_of_msg=ERROR)
            say(e.stderr.strip(), type_of_msg=ERROR_EXTENDED)
        if type_of_msg is None:
            type_of_msg = (
                ERROR_EXTENDED if isinstance(e, EspeakError) else ERROR
            )
        say(str(e), type_of_msg=type_of_msg)


def report_action_cancelled():
    say(_("The action was cancelled."), type_of_msg=INFO)


_HELPLESS = _(
        "?eEOF:%lt-%lb.\\: Use the arrow keys to scroll or press q to return "
        "to the program."
    )


def pager(what, title=None, wrap=False):
    what = what.strip()
    if wrap:
        what = what.split("\n")
        what = map(
            lambda x:
                textwrap.fill(x, window_width(), break_on_hyphens=False),
            what,
        )
        what = "\n".join(what)
    with lock:
        if title:
            print(_prompt[INFO] + title)
            print()
        if not (LINUX or WINDOWS):
            raise InternalError(UNSUPPORTED_PLATFORM)
        if WINDOWS:
            try:
                codepage = subprocess.run(
                        ["mode", "con", "cp"], shell=True, capture_output=True
                ).stdout
                codepage = int([x for x in codepage.split() if x.isdigit()][0])
                what = what.encode("cp%s" % codepage, "backslashreplace")
            except Exception as e:
                with lock:
                    report_error(
                        _(
                            "An error has occurred while trying to convert "
                            "the log to the console’s encoding."
                        )
                    )
                    say(
                        _("The output might contain wrong characters."),
                        type_of_msg=INFO,
                    )
            subprocess.run(
                "more",
                shell=True,
                input=what,
                text=isinstance(what, str),
                check=True,
            )
            print()
        else:
            subprocess.run(
                ["less", "-Ps%s" % _HELPLESS],
                input=what,
                text=True,
                check=True
            )
        print(_prompt[INFO] + _("Returning to the program."))
        print()
