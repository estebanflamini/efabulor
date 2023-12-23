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

import efabcmd
import efablogger
import efabuserinput
from efabargs import get_args


def main_loop(core):

    scripted_mode = get_args().scripted

    while True:

        user_input, parsed_command = _get_command(scripted_mode)

        if (
            parsed_command is not None
            and efabcmd.contains_quit(parsed_command)
        ):
            break_pause()
            if core.player.playing_feedback():
                core.player.stop_feedback()
            efabcmd.process(core, parsed_command)
        elif _do_not_interpret(user_input, core, scripted_mode):
            pass
        elif parsed_command:
            # Acquire lock on player to exclude text updating while
            # interpreting a command. See the _Updater class in the efabplayer
            # module for the competing lock acquisition this one is intended to
            # preclude.
            with core.player.lock:
                efabcmd.process(core, parsed_command)
        elif (
            scripted_mode
            and user_input
            and not efabcmd.is_macro(user_input)
        ):
            efablogger.say(
                efabcmd.MSG_INVALID_MACRO % user_input,
                type_of_msg=efablogger.ERROR
            )


def _get_command(scripted_mode):
    if scripted_mode:
        line = efabuserinput.getline()
        return line, (
            # In this version we only allow predefined macros to be entered:
            efabcmd.parse(line)
            if line and efabcmd.is_macro(line)
            else None
        )
    else:
        ch = efabuserinput.getch()
        return ch, efabcmd.get_parsed_command(ch) if ch else None


def _do_not_interpret(user_input, core, scripted_mode):
    if core.player.playing_feedback():
        core.player.stop_feedback()
        if not scripted_mode:
            efablogger.say(
                _(
                    "Feedback playing was stopped. Press the same key "
                    "again if you intended to run a command."
                ),
                type_of_msg=efablogger.INFO
            )
        return True
    elif pausing():
        break_pause()
        return True
    else:
        return False


_terminated_from_inside = False


def terminate(msg=None):

    global _terminated_from_inside

    if threading.current_thread() is not threading.main_thread():
        _terminated_from_inside = True
        if isinstance(msg, str) or isinstance(msg, Exception):
            efablogger.say(msg, type_of_msg=efablogger.ERROR)
        os.kill(os.getpid(), signal.SIGTERM)
    elif _terminated_from_inside:
        sys.exit(DEFAULT_ERROR_RETURNCODE)
    elif msg is None:
        sys.exit()
    elif isinstance(msg, str) or isinstance(msg, Exception):
        efablogger.say(msg, type_of_msg=efablogger.ERROR)
        sys.exit(DEFAULT_ERROR_RETURNCODE)
    elif isinstance(msg, int):
        sys.exit(msg)
    else:
        sys.exit(DEFAULT_ERROR_RETURNCODE)


def run_safely(func):
    try:
        if func is not None:
            # Perhaps it could be None during interpreter shutdown?
            func()
    except Exception as e:
        with efablogger.lock:
            efablogger.say(
                _("An uncaught exception has occurred: %s.") % e,
                type_of_msg=efablogger.ERROR,
            )
            traceback.print_exc(file=efablogger.get_file(efablogger.ERROR))
            efablogger.separate(efablogger.ERROR)
            terminate(PROGRAM_MUST_TERMINATE_NOW)


def start_daemon(func):
    t = threading.Thread(target=lambda: run_safely(func))
    t.daemon = True
    t.start()
    return t


_pause_event = threading.Event()
_pause_event.set()


def pause(timeout):
    if not timeout:
        return False
    efablogger.say(
        ("paused: %s seconds") % timeout,
        type_of_msg=efablogger.PAUSE
    )
    _pause_event.clear()
    _pause_event.wait(timeout)
    _pause_event.set()
    return True


def pausing():
    return not _pause_event.is_set()


def break_pause():
    _pause_event.set()
