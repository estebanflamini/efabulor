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

import efablogger
from efabargs import get_args
from efabcore import terminate


if TYPE_CHECKING:
    _ = gettext.gettext


_old_tty_settings = None


if LINUX:
    signal.signal(
        signal.SIGCONT,
        lambda signum, frame: set_normal()
    )
atexit.register(lambda: set_normal())


def _terminate_on_intr(do_terminate=True):
    handler = (
        lambda signum, frame: terminate(TERMINATED_BY_SIGNAL % "SIGINT")
    ) if do_terminate or get_args().scripted else signal.SIG_IGN
    signal.signal(signal.SIGINT, handler)


_terminate_on_intr()


def _no_intr(f):
    def inner(*args, **kwargs):
        _terminate_on_intr(False)
        ret = f(*args, **kwargs)
        _terminate_on_intr(True)
        return ret
    return inner


def set_raw():
    global _old_tty_settings

    if not (LINUX or WINDOWS):
        raise InternalError(UNSUPPORTED_PLATFORM)
    if WINDOWS:
        return
    elif _old_tty_settings is None:
        fd = sys.stdin.fileno()
        _old_tty_settings = termios.tcgetattr(fd)
        new_tty_settings = termios.tcgetattr(fd)
        new_tty_settings[0] &= ~termios.IXON
        new_tty_settings[3] &= ~(termios.ICANON | termios.ECHO)
        termios.tcsetattr(fd, termios.TCSANOW, new_tty_settings)


def set_normal():
    global _old_tty_settings

    if not (LINUX or WINDOWS):
        raise InternalError(UNSUPPORTED_PLATFORM)
    if WINDOWS:
        return
    elif _old_tty_settings is not None:
        termios.tcsetattr(
            sys.stdin.fileno(), termios.TCSANOW, _old_tty_settings
        )
        _old_tty_settings = None


_A_LARGE_ENOUGH_NUMBER = 42


def getch() -> Optional[str]:
    if not (LINUX or WINDOWS):
        raise InternalError(UNSUPPORTED_PLATFORM)
    set_raw()
    try:
        if LINUX:
            return str(
                os.read(sys.stdin.fileno(), _A_LARGE_ENOUGH_NUMBER),
                encoding=SYSTEM_ENCODING,
            )
        else:
            ch = msvcrt.getch()  # type: ignore
            return str(ch, encoding=SYSTEM_ENCODING)
    except (KeyboardInterrupt, EOFError, OSError):
        return None


@_no_intr
def getline(prompt: Optional[str] = None) -> Optional[str]:
    set_normal()
    try:
        return input(prompt or "")
    except (KeyboardInterrupt, EOFError, OSError):
        return None


def get_int() -> Optional[int]:
    with efablogger.lock:
        return _get_int()


def _get_int() -> Optional[int]:
    reply = getline().strip()
    efablogger.separate(efablogger.INTERACTION)
    if not reply:
        efablogger.report_action_cancelled()
        return None
    if reply.isdigit():
        return int(reply)
    else:
        efablogger.say(
            _("You must enter a positive integer."),
            type_of_msg=efablogger.ERROR
        )
        efablogger.report_action_cancelled()
        return None


@_no_intr
def confirm_action(msg: str) -> bool:
    with efablogger.lock:
        return _confirm_action(msg)


def _confirm_action(msg: str) -> bool:
    msg += " [%s/%s]" % (YES_KEY.lower(), NO_KEY.upper())
    efablogger.say(msg, type_of_msg=efablogger.INTERACTION, end=" ")
    answer = False
    while True:
        ch = (getch() or "").lower()
        if ch in [NO_KEY.lower(), YES_KEY.lower()]:
            efablogger.say(
                ch,
                type_of_msg=efablogger.INTERACTION,
                print_prompt=False
            )
            answer = ch == YES_KEY
            break
        elif ch in [chr(13), chr(10)]:
            efablogger.say(
                NO_KEY.lower(),
                type_of_msg=efablogger.INTERACTION,
                print_prompt=False,
            )
            break
    return answer


@_no_intr
def choose_mode(
    msg: str, choices: List[str], current_mode_name: str
) -> Optional[str]:
    with efablogger.lock:
        return _choose_mode(msg, choices, current_mode_name)


def _choose_mode(
    msg: str, choices: List[str], current_mode_name: str
) -> Optional[str]:

    efablogger.say(msg, type_of_msg=efablogger.INTERACTION)
    n = 1
    s = ""
    names = list(choices)
    for mode_name in names:
        mark_current = "*" if mode_name == current_mode_name else ""
        s += str(n) + ": " + mode_name + mark_current + "\n"
        n += 1
    s += "\n"
    s += _("Press 0 to cancel")
    efablogger.say(
        s,
        type_of_msg=efablogger.INTERACTION,
        wrap=False,
        print_prompt=False
    )
    while True:
        c = getline().strip() if get_args().scripted else getch()
        if c.isdigit():
            if c == "0":
                efablogger.report_action_cancelled()
                return None
            elif int(c) >= 1 and int(c) <= len(choices):
                mode_name = names[int(c) - 1]
                return mode_name
