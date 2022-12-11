#!/usr/bin/env python3

# EFABULOR: a user-friendly command-line front-end to espeak
# Copyright (C) 2021, 2022 Esteban Flamini <http://estebanflamini.com>

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

__version__ = "0.99"

# Import needed Python packages. I mostly prefer to import the module as a
# whole (instead of from module import ...) to avoid injecting names into the
# global namespace

import sys
import os
import gettext
import threading
import re
import subprocess
import signal
import textwrap
import locale
import shlex
import difflib
import time
from random import randint
import queue
import argparse
import codecs
import traceback
from ast import literal_eval
import efabregex
import efabrules
import platform

try:
    import psutil

    PSUTIL_INSTALLED = True
except ModuleNotFoundError:
    PSUTIL_INSTALLED = False

# Additional modules are imported below after determining host platform

PROGNAME = "efabulor"

EFABTRANS = sys.path[0] + "/efabtrans.py"
EFABCONV = sys.path[0] + "/efabconv.py"

locale.setlocale(locale.LC_ALL, "")

# Localisation should be easy
DOMAIN = "efabulor"
if (
  "TEXTDOMAINDIR" in os.environ
  and gettext.find(DOMAIN, os.environ["TEXTDOMAINDIR"])
):
    gettext.install(DOMAIN, os.environ["TEXTDOMAINDIR"])
elif gettext.find(DOMAIN, sys.path[0]):
    gettext.install(DOMAIN, sys.path[0])
else:
    gettext.install(DOMAIN)

PLATFORM = platform.system()

if PLATFORM in [
    "Linux",
    "Darwin",
]:
    # We will think positive, and assume this will run under macOS and related
    # OSs.
    import termios

    try:
        import readline
    except ModuleNotFoundError:
        pass
    import select

    LINUX = True
    WINDOWS = False
elif PLATFORM == "Windows":
    import msvcrt

    LINUX = False
    WINDOWS = True
    EFABTRANS = sys.executable + " " + EFABTRANS.replace("\\", "/")
    EFABCONV = sys.executable + " " + EFABCONV.replace("\\", "/")
else:
    sys.exit(
        _("Fatal error: could not determine host platform or it is "
          "unsupported.")
    )

UNSUPPORTED_PLATFORM = _("Unsupported operation for platform: %s.") % PLATFORM

# FOR TRANSLATORS: This is the keypress used to answer YES to a yes/no question
YES_KEY = _("y")
# FOR TRANSLATORS: This is the keypress used to answer NO to a yes/no question
NO_KEY = _("n")

DEFAULT_ERROR_RETURNCODE = 1

SYSTEM_ENCODING = locale.getdefaultlocale()[1]
# These will be set by CmdLineArgs._set_encoding()
INPUT_ENCODING = None
INPUT_ENCODING_SIG = None
CONFIG_ENCODING = None

LANG = None  # Will be set by CmdLineArgs._set_language()

DEFAULT_SPEED = 180
MAXSPEED = 400
MINSPEED = 10

MACRO_QUIT_ASK = "quit-ask"
MACRO_QUIT_NOW = "quit-now"
MSG_INVALID_MACRO = _("'%s' is not a valid action name.")


def staticclass(cls):
    def raise_exc(msg):
        raise TypeError(msg)

    cls.__new__ = lambda *args: raise_exc("This class is uninstantiable by "
                                          "design.")
    cls.__init_subclass__ = lambda *args: raise_exc(
        "This class is unsubclassable by design."
    )
    return cls


def mainthreadmethod(func):
    # TODO add the assertion directly to the relevant methods and eliminate
    # this decorator?
    def decorated(*args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            caller_name = func.__qualname__ + "()"
            Main.terminate(
                "Internal error: calling %s from outside the main thread is "
                "prohibited by design." % caller_name
            )
        return func(*args, **kwargs)

    return decorated


def translate_control_chars(s):
    return literal_eval('u"%s"' % s.replace('"', r"\""))


@staticclass
class Output:

    _lock = threading.RLock()

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

    _first_time = True
    _counter = 0

    _no_info = False

    @classmethod  # class Output
    def window_width(cls, target=sys.stdout):
        try:
            return (
                os.get_terminal_size(target.fileno()).columns
                - RuntimeOptions.window_width_adjustment()
            )
        except OSError:
            return (
              cls.DEFAULT_WINDOW_WIDTH
              - RuntimeOptions.window_width_adjustment()
            )

    @classmethod  # class Output
    def no_info(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._no_info
            cls._no_info = value

    @classmethod  # class Output
    def say(cls, what, type_of_msg, wrap=True, print_prompt=True, end="\n\n"):

        if not isinstance(what, str):
            Main.terminate("Internal error: called Output.say() with a "
                           "non-string")

        with cls._lock:

            if cls._no_info and type_of_msg == cls.INFO:
                return False

            target = cls._target[type_of_msg]

            if cls._first_time:
                cls._first_time = False
                print(file=target)

            what = what.strip()

            prompt = (
              cls._prompt_scripted
              if Main.scripted_mode
              else cls._prompt
            )

            if type_of_msg in [
                cls.NORMAL_EXTENDED,
                cls.INFO_EXTENDED,
                cls.ERROR_EXTENDED,
            ]:
                what = textwrap.indent(
                    what,
                    prompt[type_of_msg],
                    lambda x: True
                )
                wrap = False
            elif print_prompt:
                what = prompt[type_of_msg] + what
            if wrap:
                width = cls.window_width(target)
                if type_of_msg == cls.NORMAL:
                    width -= (
                        RuntimeOptions.left_indent()
                        + RuntimeOptions.right_indent()
                    )
                what = "\n".join(
                    textwrap.fill(
                        x, width, break_on_hyphens=False,
                        replace_whitespace=False
                    )
                    for x in what.split("\n")
                )
                if type_of_msg == cls.NORMAL:
                    what = textwrap.indent(
                        what,
                        " " * RuntimeOptions.left_indent()
                    )
            print(what, file=target, end=end)
            target.flush()
            cls._counter += 1
            return True

    @classmethod  # class Output
    def separate(cls, type_of_msg):
        with cls._lock:
            print(file=cls._target[type_of_msg])

    @classmethod  # class Output
    def get_file(cls, type_of_msg):
        return cls._target[type_of_msg]

    @classmethod  # class Output
    def get_prompt(cls, type_of_msg):
        return cls._prompt[type_of_msg]

    @classmethod  # class Output
    def get_counter(cls):
        with cls._lock:
            return cls._counter

    @classmethod  # class Output
    def get_lock(cls):
        return cls._lock

    @classmethod  # class Output
    def report_error(cls, e, type_of_msg=None):
        with cls._lock:
            if isinstance(e, subprocess.CalledProcessError):
                cls.say(
                    _(
                        "An error has occurred while executing an external "
                        "command %s."
                    )
                    % e.cmd,
                    type_of_msg=cls.ERROR,
                )
                cls.say(
                    _("The process error output is:"),
                    type_of_msg=cls.ERROR
                )
                cls.say(e.stderr.strip(), type_of_msg=cls.ERROR_EXTENDED)
            if type_of_msg is None:
                type_of_msg = (
                    cls.ERROR_EXTENDED
                    if isinstance(e, EspeakControllerError)
                    else cls.ERROR
                )
            cls.say(str(e), type_of_msg=type_of_msg)

    @classmethod  # class Output
    def report_action_cancelled(cls):
        cls.say(_("The action was cancelled."), type_of_msg=Output.INFO)

    _HELPLESS = _(
        "?eEOF:%lt-%lb.\\: Use the arrow keys to scroll or press q to return "
        "to the program."
    )

    @classmethod  # class Output
    def pager(cls, what, title=None, wrap=False):
        what = what.strip()
        if wrap:
            what = what.split("\n")
            what = map(
                lambda x:
                    textwrap.fill(
                        x,
                        cls.window_width(),
                        break_on_hyphens=False
                    ),
                what,
            )
            what = "\n".join(what)
        with cls._lock:
            if title:
                print(cls._prompt[cls.INFO] + title)
                print()
            if WINDOWS:
                try:
                    codepage = subprocess.run(
                        ["mode", "con", "cp"], shell=True, capture_output=True
                    ).stdout
                    codepage = int(
                        [x for x in codepage.split() if x.isdigit()][0]
                    )
                    what = what.encode("cp%s" % codepage, "backslashreplace")
                except Exception as e:
                    cls.report_error(
                        _(
                            "An error has occurred while trying to convert "
                            "the log to the console’s encoding."
                        )
                    )
                    cls.say(
                        _("The output might contain wrong characters."),
                        type_of_msg=cls.INFO,
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
                    ["less", "-Ps%s" % cls._HELPLESS],
                    input=what,
                    text=True,
                    check=True
                )
            print(cls._prompt[cls.INFO] + _("Returning to the program."))
            print()


class EspeakControllerError(Exception):
    pass


PSSUSPEND = None

if WINDOWS and not PSUTIL_INSTALLED:
    for program in ["pssuspend", "pssuspend64"]:
        try:
            subprocess.run(
                [program, "-"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            PSSUSPEND = program
            break
        except Exception:
            pass


class EspeakController:

    _lock = threading.RLock()

    @classmethod  # class EspeakController
    def get_lock(cls):
        return cls._lock

    _voice = None
    _speed = DEFAULT_SPEED
    _options = []

    @classmethod  # class EspeakController
    def voice(cls, value):
        with cls._lock:
            if value is None:
                return cls._voice
            cls._voice = value

    @classmethod  # class EspeakController
    def speed(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._speed
            cls._speed = value

    @classmethod  # class EspeakController
    def options(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._options
            cls._options = value

    # class EspeakController
    def __init__(self):
        self._running = False
        self._paused = False
        self._stopped = threading.Condition(self._lock)

    # class EspeakController
    def say(self, what, on_start=None):
        with self._lock:
            if self._running:
                raise EspeakControllerError(
                    "Internal error: trying to start an already running "
                    "player."
                )
            try:
                self._espeak = self._call_espeak(what)
            except Exception as e:
                raise EspeakControllerError(e) from None
            self._running = True
            self._paused = False
            if on_start:
                on_start()
            self._lock.release()
            output, errors = self._espeak.communicate()
            self._lock.acquire()
            if errors:
                errors = errors.strip()
                if self._espeak.returncode and self._running:
                    self._running = False
                    raise EspeakControllerError(errors)
                else:
                    Output.report_error(
                        errors,
                        type_of_msg=Output.ERROR_EXTENDED
                    )
            self._running = False
            self._stopped.notify()

    # class EspeakController
    def _call_espeak(self, line):
        line = re.sub(
            r"^\s*-", r"\-", line
        )  # to avoid an initial hyphen to be taken as an option
        d = ["espeak", "-s", str(self._speed)]
        if self._voice:
            d += ["-v", self._voice]
        if self._options:
            d += self._options
        d += [line]
        # In case you modify this method, be VERY careful to ensure
        # sanitization if you were to make the call through a shell.
        return subprocess.Popen(d, text=True, stderr=subprocess.PIPE)

    # class EspeakController
    def toggle(self):
        with self._lock:
            if self._running and self._espeak_still_running():
                self._paused = not self._paused
                if LINUX:
                    self._espeak.send_signal(
                        signal.SIGSTOP if self._paused else signal.SIGCONT
                    )
                    return True
                elif WINDOWS:
                    if PSUTIL_INSTALLED:
                        if self._paused:
                            psutil.Process(self._espeak.pid).suspend()
                        else:
                            psutil.Process(self._espeak.pid).resume()
                        return True
                    if not PSSUSPEND:
                        return False
                    try:
                        if self._paused:
                            subprocess.run(
                                [PSSUSPEND, str(self._espeak.pid)],
                                check=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        else:
                            subprocess.run(
                                [PSSUSPEND, "-r", str(self._espeak.pid)],
                                check=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                        return True
                    except Exception:
                        self._paused = not self._paused
                        return False
                else:
                    traceback.print_exc()
                    Main.terminate(UNSUPPORTED_PLATFORM)

    # class EspeakController
    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._espeak_still_running():
                if LINUX and self._paused:
                    # Otherwise, terminate() won't do.
                    self._espeak.send_signal(signal.SIGCONT)
                self._espeak.terminate()
            self._stopped.wait()

    # class EspeakController
    def _espeak_still_running(self):
        return self._espeak is not None and self._espeak.poll() is None

    # class EspeakController
    def running(self):
        with self._lock:
            return self._running

    # class EspeakController
    def running_and_paused(self):
        with self._lock:
            return self._running and self._paused

    # class EspeakController
    def running_and_not_paused(self):
        with self._lock:
            return self._running and not self._paused


@staticclass
class Main:

    # This class does not need a lock, because all of its methods accessing
    # state are called from the main thread.

    signal.signal(
        signal.SIGTERM,
        lambda signum, frame: Main.terminate(
            Main.TERMINATED_BY_SIGNAL % "SIGTERM"
        ),
    )
    if LINUX:
        signal.signal(
            signal.SIGHUP,
            lambda signum, frame: Main.terminate(
                Main.TERMINATED_BY_SIGNAL % "SIGHUP"
            ),
        )

    scripted_mode = False

    _termination_hooks = []

    TERMINATED_BY_SIGNAL = _("The program was terminated by signal: %s.\n")
    PROGRAM_MUST_TERMINATE_NOW = _("The program must terminate now.")
    REPORTED_ERROR_MSG = "Reported error is: %s"

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def run_safely(cls, func):
        try:
            if func is not None:
                # Perhaps it could be None during interpreter shutdown?
                func()
        except Exception as e:
            Output.say(
                _("An uncaught exception has occurred: %s.") % e,
                type_of_msg=Output.ERROR,
            )
            traceback.print_exc(file=Output.get_file(Output.ERROR))
            Output.separate(Output.ERROR)
            cls.terminate(cls.PROGRAM_MUST_TERMINATE_NOW)

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def start_daemon(cls, func):
        t = threading.Thread(target=lambda: cls.run_safely(func))
        t.daemon = True
        t.start()
        return t

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def register_termination_hook(cls, hook):
        cls._termination_hooks.append(hook)

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def pause(cls, timeout):
        if not timeout:
            return
        with Output.get_lock():
            if cls.scripted_mode:
                # Ending a pause interval is the GUI's responsibility
                Output.say(str(timeout), type_of_msg=Output.PAUSE)
                UserInput.readline()
            else:
                Output.say(
                    _("paused: %s seconds") % timeout,
                    type_of_msg=Output.INTERACTION
                )
                ch = UserInput.getch(timeout)
                if KeyBindings.is_bound_to_quit_command(ch):
                    Commands.process(KeyBindings.get_parsed_command(ch))

    _event_queue = queue.Queue()

    # If you add new event types here, you can assign them any value, but be
    # careful to ensure no values are repeated.
    INPUT_FILE_CHANGED = "IFC"
    SUBST_RULES_FILE_CHANGED = "SRFC"
    NEW_SUBSTITUTIONS_LOADED = "NSL"
    TEXT_LOADING_SUCCESS = "TLS"
    TEXT_LOADING_ERROR = "TLE"
    LINE_READING_ENDED = "LRE"
    SPOKEN_FEEDBACK_ENDED = "SFE"
    TERMINATION_MESSAGE = "TM"

    WILL_CONTINUE = _(
        "The player will stop now. If you restart the player, the program "
        "will continue as if the text was not modified."
    )

    @classmethod  # class Main
    def event(cls, evt, data=None):
        cls._event_queue.put((evt, data))

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def run(cls):

        text_is_not_loaded_yet = True

        while True:
            if cls.scripted_mode:
                parsed_command = None
                line = UserInput.readline(0.1)
                if line:
                    line = line.strip()
                    if not Commands.is_macro(line):
                        Output.say(
                            MSG_INVALID_MACRO % line,
                            type_of_msg=Output.ERROR
                        )
                    else:
                        parsed_command = Commands.parse(line)
            else:
                ch = UserInput.getch(0.1)
                parsed_command = KeyBindings.get_parsed_command(ch)
                if (
                  ch is not None
                  and TrackingController.spoken_feedback_running()
                ):
                    TrackingController.stop_playing_feedback()
                    if not KeyBindings.is_bound_to_quit_command(ch):
                        parsed_command = None
                        Output.say(
                            _(
                                "Feedback playing was stopped. Press the same "
                                "key again if you intended to run the command "
                                "instead."
                            ),
                            type_of_msg=Output.INFO,
                        )

            if parsed_command:
                Commands.process(parsed_command)

            if not cls._event_queue.empty():
                evt, data = cls._event_queue.get()
                if evt == cls.INPUT_FILE_CHANGED:
                    if (
                      Player.running()
                      or RuntimeOptions.reload_when_not_playing()
                    ):
                        InputTextLoader.start()
                    else:
                        cls._schedule_delayed_reload()
                elif evt == cls.SUBST_RULES_FILE_CHANGED:
                    Substitutions.reload()
                elif evt == cls.NEW_SUBSTITUTIONS_LOADED:
                    Player.substitution_rules_changed()
                elif evt == cls.TEXT_LOADING_SUCCESS:
                    text, lines = data
                    if not text or not lines:
                        # This should never happen, but we add the extra check
                        # for the sake of robustness.
                        cls.event(cls.TEXT_LOADING_ERROR)
                        continue
                    Player.lines(lines)
                    TrackingController.register(text, lines)
                    if text_is_not_loaded_yet:
                        text_is_not_loaded_yet = False
                        Player.line_number(
                            RuntimeOptions.sequence_mode().first(),
                            showline=False
                        )
                        FileMonitor.start()
                        if RuntimeOptions.sequence_mode() is SEQUENCE_MODIFIED:
                            Output.say(
                                _("Waiting for changes."),
                                type_of_msg=Output.INFO
                            )
                        else:
                            cls.pause(RuntimeOptions.pause_before())
                            Player.start()
                elif evt == cls.TEXT_LOADING_ERROR:
                    if not Player.text_is_loaded():
                        cls.terminate()
                    else:
                        Output.say(cls.WILL_CONTINUE, type_of_msg=Output.INFO)
                        Player.stop()
                elif evt in [
                  cls.LINE_READING_ENDED,
                  cls.SPOKEN_FEEDBACK_ENDED,
                ]:
                    # Here data contains a function call that the generator of
                    # the events wants to have executed in the main thread.
                    data()
                elif evt == cls.TERMINATION_MESSAGE:
                    # This is from a previous implementation of
                    # Main.terminate(), and should never execute, but we leave
                    # it just in case someday we want to reimplement
                    # termination by event.
                    cls.terminate(data)

    @classmethod  # class Main
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _schedule_delayed_reload(cls):
        Output.say(
            _("The input file will be reloaded upon restart."),
            type_of_msg=Output.INFO
        )
        spoken_msg = SpokenFeedback.get_message("reload-delayed")
        if spoken_msg:
            EspeakController().say(spoken_msg)
        Player.reload_required()

    _terminated_from_inside = threading.Event()

    # Tampering with the following method can break the @mainthreadmethod
    # decorator, and in fact, the proper termination of the program.
    @classmethod  # class Main
    def terminate(cls, msg=None):
        if threading.current_thread() is threading.main_thread():
            if cls._terminated_from_inside.is_set():
                while not cls._event_queue.empty():
                    evt, data = cls._event_queue.get()
                    if evt == cls.TERMINATION_MESSAGE:
                        msg = data
                        break
            if msg and isinstance(msg, str):
                Output.say(msg, type_of_msg=Output.ERROR)
            for hook in cls._termination_hooks:
                hook()
            if msg:
                if isinstance(msg, int):
                    sys.exit(msg)
                else:
                    sys.exit(DEFAULT_ERROR_RETURNCODE)
            else:
                sys.exit(0)
        else:
            cls._terminated_from_inside.set()
            cls.event(cls.TERMINATION_MESSAGE, msg)
            os.kill(os.getpid(), signal.SIGTERM)
            # The following line is needed to terminate the calling thread, do
            # not remove it.
            sys.exit()


@staticclass
class Player:

    # Most of the state-accessing code of this class is called only from the
    # main thread. A lock is provided below for some critical sections of
    # multithreaded code.

    _text_player = EspeakController()

    Main.register_termination_hook(_text_player.stop)

    _text = None
    _lines = []

    _line_to_be_read = None

    _reload_required = False

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def lines(cls, value=None):
        if value is None:
            return cls._lines
        cls._lines = value
        if cls._line_number >= len(cls._lines):
            cls.line_number(len(cls._lines) - 1, showline=False)
        cls._reload_required = False

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def text_is_loaded(cls):
        return len(cls._lines) > 0

    _line_number = 0
    _at_eol = False

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def line_number(cls, value=None, showline=True):
        if value is None:
            return cls._line_number
        if value < 0:
            value = 0
        elif value >= len(cls._lines):
            value = len(cls._lines) - 1
        if (
            value != cls._line_number
            and RuntimeOptions.stop_after_current_line()
            and RuntimeOptions.reset_scheduled_stop_after_moving()
        ):
            RuntimeOptions.stop_after_current_line(False, say_it=True)
        cls._line_number = value
        cls._at_eol = False
        cls.refresh_current_line()
        cls.update_player()
        if showline:
            cls.showline()

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def at_eol(cls, value=None):
        return cls._at_eol

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def refresh_current_line(cls):
        if not cls._lines:
            return False
        old_line_to_be_read = cls._line_to_be_read
        line = cls._lines[cls._line_number]
        cls._line_to_be_read = (
            Substitutions.apply(line) if RuntimeOptions.apply_subst() else line
        )
        return old_line_to_be_read != cls._line_to_be_read

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def substitution_rules_changed(cls):
        if not cls._lines:
            return
        if cls.refresh_current_line():
            a = cls._text_player.running_and_not_paused()
            b = RuntimeOptions.restart_after_substitution_change()
            Player.stop()
            Player.reset_pointer()
            if a or b:
                Output.say(
                    _("New substitution rules apply to this line. "
                      "Restarting."),
                    type_of_msg=Output.INFO,
                )
                msg = SpokenFeedback.get_message("subst-changed")
                if msg:
                    while (
                        TrackingController.spoken_feedback_running()
                    ):  # It should be always False, but just in case
                        time.sleep(0.1)
                    EspeakController().say(msg)
                Player.start()
            else:
                Output.say(
                    _(
                        "New substitutions will be applied when reading is "
                        "restarted."
                    ),
                    type_of_msg=Output.INFO,
                )
        else:
            Output.say(
                _("New substitution rules do not affect this line."),
                type_of_msg=Output.INFO,
            )

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def reload_required(cls):
        cls._reload_required = True

    _lock = threading.RLock()

    _running = False
    _paused = False
    _started = threading.Event()
    _stopped = threading.Condition(_lock)

    _never_said_anything = True

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def start(cls):
        if cls._text_player.running():
            return
        with cls._lock:
            if cls._at_eol:
                cls.line_number(RuntimeOptions.sequence_mode().next())
                cls._at_eol = False
            cls._running = True
            cls._paused = False
        cls.showline()
        cls._started.clear()
        line = cls._line_to_be_read
        Main.start_daemon(lambda: cls._say_line(line))
        cls._never_said_anything = False
        cls._started.wait()
        if cls._reload_required:
            # In case the file was modified while the player was paused
            cls._reload_required = False
            InputTextLoader.start()

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def never_said_anything(cls):
        return cls._never_said_anything

    @classmethod  # class Player
    def _say_line(cls, line):
        an_error_has_occurred = False
        try:
            cls._text_player.say(line, on_start=cls._started.set)
        except EspeakControllerError as e:
            with Output.get_lock():
                Output.say(
                    _("An error has occurred while trying to run espeak."),
                    type_of_msg=Output.ERROR,
                )
                Output.report_error(e)
                Output.say(
                    _("The reading is stopped, you can try to restart it."),
                    type_of_msg=Output.INFO,
                )
            an_error_has_occurred = True
        with cls._lock:
            if not cls._running:
                cls._stopped.notify()
            elif an_error_has_occurred:
                cls._running = False
                # Set the flag in case .say() didn't set it and start() is
                # waiting.
                cls._started.set()
            else:
                Main.event(Main.LINE_READING_ENDED, cls._continue)

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _continue(cls):
        cls._lock.acquire()
        if cls._paused or not cls._running:
            cls._lock.release()
            return
        sequence_mode = RuntimeOptions.sequence_mode()
        if sequence_mode.eof():
            if (
              RuntimeOptions.close_at_end()
              and sequence_mode is SEQUENCE_NORMAL
            ):
                cls._lock.release()
                Main.terminate()
            else:
                cls._at_eol = True
                cls._running = False
                cls._lock.release()
        elif (
          RuntimeOptions.stop_after_current_line()
          or RuntimeOptions.stop_after_each_line()
        ):
            cls._at_eol = True
            cls._running = False
            cls._lock.release()
            with Output.get_lock():
                if RuntimeOptions.stop_after_current_line():
                    RuntimeOptions.stop_after_current_line(False, say_it=False)
                if RuntimeOptions.stop_after_each_line():
                    Output.say(
                        _("The player is stopping at the end of each line."),
                        type_of_msg=Output.INFO,
                    )
        else:
            cls._lock.release()
            Main.pause(RuntimeOptions.pause_between())
            cls.line_number(sequence_mode.next())
            cls.start()

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def stop(cls):
        with cls._lock:
            if not cls._running:
                return
            cls._running = False
            cls._paused = False
            if cls._text_player.running():
                cls._text_player.stop()
                cls._stopped.wait()

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def reset_pointer(cls, say_it=True):
        if cls._at_eol:
            cls._at_eol = False
            if say_it:
                Output.say(
                    _("The player was reset to the beginning of the current "
                      "line."),
                    type_of_msg=Output.INFO,
                )

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def toggle(cls):
        with cls._lock:
            if cls._running:
                cls._paused = not cls._paused
                if cls._text_player.running():
                    if not cls._text_player.toggle():
                        # Can be False in Windows
                        cls._paused = not cls._paused
                elif not cls._paused:
                    cls._continue()
                return
            # If we are at the end of the file, then _at_eol can be True. In
            # that case, let's just read the last line again.
            if RuntimeOptions.sequence_mode().eof():
                cls._at_eol = False
        Main.pause(RuntimeOptions.pause_before())
        cls.start()
        if cls._reload_required:
            # In case the file was modified while the player was paused
            cls._reload_required = False
            InputTextLoader.start()

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def running(cls):
        with cls._lock:
            return cls._running

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def running_and_not_paused(cls):
        with cls._lock:
            return cls._running and not cls._paused

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def update_player(cls, requested_by_user=False):
        if RuntimeOptions.no_update_player() and not requested_by_user:
            return
        if cls._text_player.running_and_not_paused():
            cls.stop()
            cls.start()
        elif cls._text_player.running_and_paused():
            cls.stop()

    _last_shown_line = None

    @classmethod  # class Player
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def showline(cls, requested_by_user=False):
        if RuntimeOptions.no_showline():
            return False
        if RuntimeOptions.no_echo() and not requested_by_user:
            return False
        t = (
            cls._line_to_be_read
            if RuntimeOptions.show_subst()
            else cls._lines[cls._line_number]
        )
        if RuntimeOptions.show_line_number():
            lineno = str(cls._line_number + 1)
            tot = (
                ("/" + str(len(cls._lines)))
                if RuntimeOptions.show_total_lines()
                else ""
            )
            t = "<%s%s> %s" % (lineno, tot, t)
        # If show_line() gets called again to print the same line, and nothing
        # else has been printed by Output.say() since the last call from
        # show_line(), do not print the same line again, unless
        # requested_by_user is True.
        # CAUTION: do not try to simplify by setting a variable
        # this_call = (cls._line_number, t, Output.get_counter())
        # here and assigning it to _last_shown_line below, because the output
        # counter will get incremented after a successful call to Output.say().
        if (
            cls._line_number,
            t,
            Output.get_counter(),
        ) == cls._last_shown_line and not requested_by_user:
            return False
        if Output.say(t, type_of_msg=Output.NORMAL):
            # If the call to Output.say() is successful, update
            # _last_shown_line.
            cls._last_shown_line = (cls._line_number, t, Output.get_counter())
            return True
        return False


@staticclass
class Commands:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    _macros = None

    # Macros define a mapping from identifiers to (possibly compound) commands
    # in the internal scripting language.

    # The scripting language is still immature, so for the time being we will
    # keep it undocumented and hidden from the end users.
    # Macros allow us to do that, and at the same time they make it easier for
    # the end users to modify the default key bindings without having to know
    # anything about the scripting language.

    # May I be honest with you? I created the scripting language to give users
    # some flexibility to redefine the standard behaviour of the program (at
    # least, the part of the program which responds to users’ keystrokes), but
    # now I'm rather unsatisfied with my design. At this point, it is easier to
    # add this macro-thing as a wrapper around it than to redesign it or remove
    # it at once.

    # By hiding the scripting language from the end users at this stage, I buy
    # time to maybe find a better implementation, while still giving the users
    # some freedom to reconfigure key bindings if they wish.

    # Should I discover that no end users will ever need to use the scripting
    # language, the macros also provide some kind of buffer, whereby the
    # scripting language can be safely removed by providing hardcoded methods
    # to implement the macros’ semantics.

    # Meanwhile...

    # In this version, only the program itself can define macros, and only
    # macros can be bound to keystrokes in external key bindings files.
    # (However, the program will try to interpret undefined macros as
    # non-compound commands in the target scripting language. This is yet
    # another hack, totally hidden from the user).

    # In future versions, we might allow the user to define macros and/or
    # bindings directly in the scripting language (once it and the underlying
    # classes’ interfaces are better designed).

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _define_macros(cls):
        # We put this code inside a method so we can call it after
        # PlayerCommands (on which it depends) was defined.
        # This is yet another hack, to avoid having to move code around.
        # This type of hacks will be probably not be necessary if and when we
        # convert the static classes into proper singletons.
        cls._macros = {
            MACRO_QUIT_NOW:
                "stop ; " + cls.QUIT_CMD,

            MACRO_QUIT_ASK:
                "stop ; " + cls.ASK_N_QUIT_CMD,

            "restart-and-stop":
                "modifyopt stop-after-current-line true ; restart",

            "stop-and-reset-pointer":
                "stop ; resetpointer",

            "first-stop":
                "stop ; first",

            "last-stop":
                "stop ; last",

            "next-stop":
                "stop ; next",

            "stop-or-previous":
                "stoporprevious",

            "toggle-stop-after-current-line":
                "modifyopt stop-after-current-line",

            "toggle-stop-after-each-line":
                "modifyopt stop-after-each-line",

            "toggle-apply-subst":
                "modifyopt apply-subst then refreshline then updateplayer",

            "toggle-show-subst":
                "modifyopt show-subst then showline",

            "log-subst":
                "logsubst",

            "log-transform":
                "logtransform",

            "cycle-line-number":
                "lineno ; showline",

            "show-line":
                "showline",

            "search-plain-case-insensitive":
                "noecho find %s %s then showline"
                % (PlayerCommands.SEARCH_PLAIN, PlayerCommands.SEARCH_CI),

            "search-plain-case-sensitive":
                "noecho find %s %s then showline"
                % (PlayerCommands.SEARCH_PLAIN, PlayerCommands.SEARCH_CS),

            "search-regex-case-insensitive":
                "noecho find %s %s then showline"
                % (PlayerCommands.SEARCH_REGEX, PlayerCommands.SEARCH_CI),

            "search-regex-case-sensitive":
                "noecho find %s %s then showline"
                % (PlayerCommands.SEARCH_REGEX, PlayerCommands.SEARCH_CS),

            "search":
                "noecho find then showline",

            "find-next":
                "noecho findnext then showline",

            "find-next-stop":
                "noecho findnext then stop and showline",

            "find-prev":
                "noecho findprev then showline",

            "find-prev-stop":
                "noecho findprev then stop and showline",

            "go-line":
                "goline",

            "prev-change":
                "noecho noupdateplayer goprevchange then modifyopt "
                "stop-after-current-line true and restart",

            "next-change":
                "noecho noupdateplayer gonextchange then modifyopt "
                "stop-after-current-line true and restart",

            "random":
                "noinfo modifyopt stop-after-current-line false ; noecho "
                "noupdateplayer gorandom ; modifyopt stop-after-current-line "
                "true ; restart",

            "faster":
                "changespeed +10 then noecho updateplayer",

            "slower":
                "changespeed -10 then noecho updateplayer",

            "open-input-file":
                "openinputfile",

            "open-input-file-stop":
                "stop ; openinputfile",

            "open-subst":
                "opensubst",

            "open-transform":
                "opentransform",

            "open-cl-monitored-file":
                "openclmonfile",

            "open-shell":
                "stop ; openshell",

            "check-files":
                "checkfiles",

            "choose-tracking-mode":
                "stop ; modifyopt tracking-mode",

            "choose-sequence-mode":
                "stop ; modifyopt sequence-mode",

            "choose-feedback-mode":
                "stop ; modifyopt feedback-mode",

            "internal-shell":
                "stop ; cmd",

            "special-mode":
                "stop ; modifyopt tracking-mode forward ; modifyopt "
                "feedback-mode full ; modifyopt stop-after-each-line true",

            "normal-mode":
                "stop ; modifyopt tracking-mode backward ; modifyopt "
                "feedback-mode minimum ; modifyopt stop-after-each-line false",

            "show-input-cmd-stop":
                "stop ; showinputcmd",

            "show-input-cmd":
                "showinputcmd",
        }
        # Macro names which are identical to their assigned commands:
        for m in [
          "toggle", "restart", "first", "last", "next", "previous", "reload"
        ]:
            cls._macros[m] = m

    CMD_SEPARATOR_LOW = ";"
    CMD_SEPARATOR_HIGH = "and"
    CMD_SEPARATOR_THEN = "then"
    CMD_SEPARATOR_ONMOVETHEN = "onmovethen"
    CMD_PREFIX_NOECHO = "noecho"
    CMD_PREFIX_NOINFO = "noinfo"
    CMD_PREFIX_NOUPDATEPLAYER = "noupdateplayer"

    ASK_N_QUIT_CMD = "quit"
    QUIT_CMD = "QUIT"

    # This is the internal scripting language. It is an experimental feature.
    # Beware that it might change or be removed altogether in future versions,
    # without previous notice.

    # Commands which can only be executed once the text has been read. I prefer
    # to use lambdas even when unnecessary for the sake of readability, and
    # also because it allows moving this code around (i.e., before the actual
    # definition of functions) without breaking it.
    _bindings_player = {
        "toggle": lambda: Player.toggle(),
        "restart": lambda: PlayerCommands.restart(),
        "stop": lambda: Player.stop(),
        "resetpointer": lambda: Player.reset_pointer(),
        "refreshline": lambda: Player.refresh_current_line(),
        "updateplayer": lambda: Player.update_player(requested_by_user=True),
        "first": lambda: PlayerCommands.first(),
        "last": lambda: PlayerCommands.last(),
        "next": lambda: PlayerCommands.next(),
        "previous": lambda: PlayerCommands.previous(),
        "stoporprevious": lambda: PlayerCommands.stop_or_previous(),
        "modifyopt": lambda *x: RuntimeOptions.modify(*x),
        "getopt": lambda x: RuntimeOptions.get(x),
        "logsubst": lambda: Substitutions.show_log(),
        "logtransform": lambda: InputTextLoader.log_transformation_rules(),
        "lineno": lambda: PlayerCommands.cycle_line_number_printing(),
        "showline": lambda: Player.showline(requested_by_user=True),
        "changespeed": lambda x: PlayerCommands.change_speed(int(x)),
        "goline": lambda *x: PlayerCommands.go_line(*map(int, x)),
        "find": lambda *x: PlayerCommands.find(*x),
        "findnext": lambda: PlayerCommands.find_next(),
        "findprev": lambda: PlayerCommands.find_previous(),
        "gorandom": lambda: PlayerCommands.go_random(),
        "reload": lambda: InputTextLoader.start(),
        "goprevchange": lambda: PlayerCommands.go_modified(False),
        "gonextchange": lambda: PlayerCommands.go_modified(True),
        "checkfiles": lambda: FileMonitor.check_files(say_it=True),
    }

    # Commands which can be executed even before the text has been read
    _bindings_general = {
        "sh": lambda *x: NonPlayerCommands.run_in_shell(*x),
        "openshell": lambda: NonPlayerCommands.open_shell(),
        "openfile": lambda x: NonPlayerCommands.open_file(x),
        "openinputfile": lambda: NonPlayerCommands.open_input_file(),
        "opentransform": lambda: NonPlayerCommands.choose_and_open_file(
            InputTextLoader.transformation_rule_files(),
            _("No transformation rules were given."),
        ),
        "opensubst": lambda: NonPlayerCommands.choose_and_open_file(
            Substitutions.rule_files(), _("No substitution rules were given.")
        ),
        "openclmonfile": lambda: NonPlayerCommands.choose_and_open_file(
            CmdLineArgs.monitored_files(),
            _("No command-line monitored files were given."),
        ),
        "showinputcmd": lambda: NonPlayerCommands.show_input_command(),
        "info": lambda *x: Output.say(" ".join(x), type_of_msg=Output.INFO),
        "pause": lambda *x: Main.pause(
            int(x[0]) if x else RuntimeOptions.pause_before()
        ),
        "cmd": lambda: NonPlayerCommands.command_loop(),
        ASK_N_QUIT_CMD: lambda: NonPlayerCommands.quit(
          ask_for_confirmation=True
        ),
        QUIT_CMD: lambda: NonPlayerCommands.quit(ask_for_confirmation=False),
    }

    MALFORMED_COMMAND = _("The following command is wrong: %s. Reported error "
                          "is: %s.")
    WRONG_COMMAND = _("The following command is wrong: %s")
    WRONG_MACRO = _("The following macro/action is wrong: <%s>")
    UNSUCCESFUL_COMMAND = _("The following command failed: %s. Reported error "
                            "is: %s.")

    _separators = [
        CMD_SEPARATOR_LOW,
        CMD_SEPARATOR_HIGH,
        CMD_SEPARATOR_THEN,
        CMD_SEPARATOR_ONMOVETHEN,
    ]
    _non_conditional_separators = [CMD_SEPARATOR_LOW, CMD_SEPARATOR_HIGH]
    _prefixes = [
      CMD_PREFIX_NOECHO, CMD_PREFIX_NOINFO, CMD_PREFIX_NOUPDATEPLAYER
    ]

    # TODO: classify commands by using an attribute in the above binding
    # dictionaries. Then, create the following three lists by comprehension.

    _commands_with_no_args = [
        "toggle",
        "restart",
        "stop",
        "resetpointer",
        "refreshline",
        "updateplayer",
        "first",
        "last",
        "next",
        "previous",
        "stoporprevious",
        "logsubst",
        "logtransform",
        "lineno",
        "showline",
        "findnext",
        "findprev",
        "reload",
        "goprevchange",
        "gonextchange",
        "gorandom",
        "checkfiles",
        "openinputfile",
        "opentransform",
        "opensubst",
        "openclmonfile",
        "openshell",
        "showinputcmd",
        "cmd",
        ASK_N_QUIT_CMD,
        QUIT_CMD,
    ]

    _commands_with_or_without_args = ["find", "goline", "pause", "sh"]
    _commands_which_accept_an_int = ["goline", "pause", "changespeed"]

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def is_macro(cls, name):
        if not (name.startswith("<") and name.endswith(">")):
            return False
        name = name[1:-1]
        if cls._macros is None:
            cls._define_macros()
        return name in cls._macros

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def parse(cls, cmd):
        cmd = cmd.strip()

        if not cmd:
            return None

        if cls.is_macro(cmd):
            return cls._parse_macro(cmd[1:-1])

        try:
            ret = cls._parse(shlex.split(cmd))
            if not ret:
                Output.say(cls.WRONG_COMMAND % cmd, type_of_msg=Output.ERROR)
            return ret
        except ValueError as e:
            Output.say(
                cls.MALFORMED_COMMAND % (cmd, e),
                type_of_msg=Output.ERROR
            )
            return None

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _parse_macro(cls, macro):
        if macro in cls._macros:
            return cls.parse(cls._macros[macro])
        Output.say(cls.WRONG_MACRO % macro, type_of_msg=Output.ERROR)
        return None

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _parse(cls, cmd):
        if not cmd:
            return None
        elif cls.CMD_SEPARATOR_LOW in cmd:
            return cls._parse_with_separator(cls.CMD_SEPARATOR_LOW, cmd)
        elif cls.CMD_SEPARATOR_THEN in cmd:
            return cls._parse_with_separator(cls.CMD_SEPARATOR_THEN, cmd)
        elif cls.CMD_SEPARATOR_ONMOVETHEN in cmd:
            return cls._parse_with_separator(cls.CMD_SEPARATOR_ONMOVETHEN, cmd)
        elif cls.CMD_SEPARATOR_HIGH in cmd:
            return cls._parse_with_separator(cls.CMD_SEPARATOR_HIGH, cmd)
        elif cmd[0] in cls._prefixes:
            return cls._parse_with_prefix(cmd)
        else:
            return cls._parse_simple(cmd)

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _parse_with_separator(cls, separator, cmd):
        n = cmd.index(separator)
        branch1 = cls._parse(cmd[0:n])
        branch2 = cls._parse(cmd[n+1:])
        if branch1 and branch2:
            return [separator, branch1, branch2]
        return None

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _parse_with_prefix(cls, cmd):
        branch = cls._parse(cmd[1:])
        if branch:
            return cmd
        return None

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _parse_simple(cls, cmd):

        if not cmd:
            return None

        verb, *args = cmd

        if not args and verb in (
            cls._commands_with_no_args + cls._commands_with_or_without_args
        ):
            return cmd

        if verb == "sh":
            return cmd if len(args) == 1 else None
        elif verb == "find":
            if len(args) > 3:
                return None
            if len(args) >= 2 and args[1] not in [
                PlayerCommands.SEARCH_CI,
                PlayerCommands.SEARCH_CS,
            ]:
                return None
            if len(cmd) >= 1 and args[0] not in [
                PlayerCommands.SEARCH_PLAIN,
                PlayerCommands.SEARCH_REGEX,
            ]:
                return None
            if len(args) == 3 and args[0] == PlayerCommands.SEARCH_REGEX:
                try:
                    re.compile(args[2])
                except Exception as e:
                    Output.say(
                        cls.MALFORMED_COMMAND % (cmd, e),
                        type_of_msg=Output.ERROR
                    )
                    return None
            return cmd
        elif verb == "info":
            return cmd if args else None
        elif verb == "modifyopt":
            if not args or not RuntimeOptions.valid_name(args[0]):
                return None
            if len(args) == 1:
                return cmd
            if len(args) > 2:
                return None
            if RuntimeOptions.valid_option(args[0], args[1]):
                return cmd
            return None
        elif verb == "getopt":
            if not args or not RuntimeOptions.valid_name(args[0]):
                return None
            return cmd if len(args) == 1 else None
        if len(args) == 1:
            if verb in cls._commands_which_accept_an_int:
                if verb == "changespeed":
                    return cmd if re.match(r"[+-]?\d+$", args[0]) else None
                elif args[0].isdigit() and int(args[0]) > 0:
                    return cmd
                return None
            elif verb == "openfile":
                return cmd
        return None

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def process(cls, cmd):
        if not cmd:
            return False
        if cmd[0] in [cls.CMD_SEPARATOR_HIGH, cls.CMD_SEPARATOR_LOW]:
            return cls._process_separator(cmd)
        elif cmd[0] == cls.CMD_SEPARATOR_THEN:
            return cls._process_then(cmd)
        elif cmd[0] == cls.CMD_SEPARATOR_ONMOVETHEN:
            return cls._process_onmovethen(cmd)
        elif cmd[0] == cls.CMD_PREFIX_NOECHO:
            return cls._process_noecho(cmd)
        elif cmd[0] == cls.CMD_PREFIX_NOINFO:
            return cls._process_noinfo(cmd)
        elif cmd[0] == cls.CMD_PREFIX_NOUPDATEPLAYER:
            return cls._process_noupdateplayer(cmd)
        else:
            return cls._process_simple(cmd)

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_separator(cls, cmd):
        cls.process(cmd[1])
        return cls.process(cmd[2])

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_then(cls, cmd):
        if cls.process(cmd[1]):
            return cls.process(cmd[2])
        return False

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_onmovethen(cls, cmd):
        ct = Player.line_number()
        cls.process(cmd[1])
        if ct != Player.line_number():
            return cls.process(cmd[2])
        return False

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_noecho(cls, cmd):
        b = RuntimeOptions.no_echo()
        RuntimeOptions.no_echo(True)
        ret = cls.process(cmd[1:])
        RuntimeOptions.no_echo(b)
        return ret

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_noinfo(cls, cmd):
        with Output.get_lock():
            b = Output.no_info()
            Output.no_info(True)
            ret = cls.process(cmd[1:])
            Output.no_info(b)
        return ret

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_noupdateplayer(cls, cmd):
        b = RuntimeOptions.no_update_player()
        RuntimeOptions.no_update_player(True)
        ret = cls.process(cmd[1:])
        RuntimeOptions.no_update_player(b)
        return ret

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _process_simple(cls, cmd):
        cmd, *args = cmd
        try:
            if cmd in cls._bindings_general:
                action = cls._bindings_general[cmd]
                return action(*args)
            elif cmd in cls._bindings_player:
                if Player.text_is_loaded():
                    action = cls._bindings_player[cmd]
                    return action(*args)
                else:
                    return False
            else:
                raise KeyError(_("Unknown command"))
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            Output.say(
                cls.UNSUCCESFUL_COMMAND % (cmd, e),
                type_of_msg=Output.ERROR
            )
            return False

    @classmethod  # class Commands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def contains_quit(cls, what):
        if isinstance(what, str):
            return what in [cls.QUIT_CMD, cls.ASK_N_QUIT_CMD]
        elif what[0] in cls._non_conditional_separators:
            # Both the antecedent and the consequent get executed.
            return cls.contains_quit(what[1]) or cls.contains_quit(what[2])
        elif what[0] in cls._separators:
            # We cannot be sure the consequent will be executed,
            # so only check the antededent
            return cls.contains_quit(what[1])
        elif what[0] in cls._prefixes:
            return cls.contains_quit(what[1:])
        else:
            # Just check the verb of the command.
            return cls.contains_quit(what[0])


@staticclass
class PlayerCommands:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def restart():
        if Player.running():
            Player.stop()
        elif Player.at_eol():
            Player.reset_pointer(False)
        Player.start()

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def first():
        sequence_mode = RuntimeOptions.sequence_mode()
        if sequence_mode.empty():
            Output.say(sequence_mode.msg_empty, type_of_msg=Output.INFO)
            return False
        elif sequence_mode.bof():
            Output.say(sequence_mode.msg_bof, type_of_msg=Output.INFO)
            return False
        else:
            Output.say(sequence_mode.msg_first, type_of_msg=Output.INFO)
            Player.line_number(sequence_mode.first())
            return True

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def last():
        sequence_mode = RuntimeOptions.sequence_mode()
        if sequence_mode.empty():
            Output.say(sequence_mode.msg_empty, type_of_msg=Output.INFO)
            return False
        elif sequence_mode.eof():
            Output.say(sequence_mode.msg_eof, type_of_msg=Output.INFO)
            return False
        else:
            Output.say(sequence_mode.msg_last, type_of_msg=Output.INFO)
            Player.line_number(sequence_mode.last())
            return True

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def next():
        sequence_mode = RuntimeOptions.sequence_mode()
        if sequence_mode.empty():
            Output.say(sequence_mode.msg_empty, type_of_msg=Output.INFO)
            return False
        elif sequence_mode.eof():
            Output.say(sequence_mode.msg_eof, type_of_msg=Output.INFO)
            return False
        else:
            Player.line_number(sequence_mode.next())
            return True

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def previous():
        sequence_mode = RuntimeOptions.sequence_mode()
        if sequence_mode.empty():
            Output.say(sequence_mode.msg_empty, type_of_msg=Output.INFO)
            return False
        elif sequence_mode.bof():
            Output.say(sequence_mode.msg_bof, type_of_msg=Output.INFO)
            return False
        else:
            Output.say(_("Back one line."), type_of_msg=Output.INFO)
            Player.line_number(sequence_mode.previous())
            return True

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def stop_or_previous(cls):
        if Player.running_and_not_paused():
            Player.stop()
            return True
        else:
            return cls.previous()

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def go_line(line_number=None):
        with Output.get_lock():
            if line_number is None:
                Player.stop()
                Output.say(_("Go to line:"), type_of_msg=Output.INTERACTION)
                line_number = UserInput.get_int()
                if line_number is None:
                    return False
            if line_number < 1 or line_number > len(Player.lines()):
                Output.say(
                    _("You must enter a line number between 1 and %s.")
                    % len(Player.lines()),
                    type_of_msg=Output.ERROR,
                )
                return False
            elif Player.line_number() == line_number - 1:
                Output.say(
                    _("The player is already at line %s.") % line_number,
                    type_of_msg=Output.INFO,
                )
                return True
            else:
                Player.line_number(line_number - 1)
                return True

    _find_what = None
    _find_re = None

    SEARCH_PLAIN = "plain"
    SEARCH_REGEX = "regex"
    SEARCH_CI = "case-insensitive"
    SEARCH_CS = "case-sensitive"

    MSG_ENTER_PLAIN = _("Enter a search string (press Enter to cancel):")
    MSG_ENTER_REGEX = _(
        "Enter a regular expression, without delimiters (press Enter to "
        "cancel):"
    )
    MSG_CASE_SENS = _("Case sensitivity is: %s")

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def find(cls, mode=None, cs=None, what=None):
        if not mode or not cs or not what:
            Player.stop()

        with Output.get_lock():
            if not mode:
                mode = UserInput.choose_mode(
                    _("Choose a search mode:"),
                    [cls.SEARCH_PLAIN, cls.SEARCH_REGEX],
                    None,
                )
                if not mode:
                    return False
                Output.say(
                    _("Search mode is: %s") % mode,
                    type_of_msg=Output.INFO
                )
            show_cs = True
            if not cs:
                cs = UserInput.choose_mode(
                    _("Choose a case sensitivity mode:"),
                    [cls.SEARCH_CI, cls.SEARCH_CS],
                    None,
                )
                if not cs:
                    return False
                Output.say(cls.MSG_CASE_SENS % cs, type_of_msg=Output.INFO)
                show_cs = False
            if not what:
                if show_cs:
                    Output.say(cls.MSG_CASE_SENS % cs, type_of_msg=Output.INFO)
                Output.say(
                    cls.MSG_ENTER_PLAIN
                    if mode == cls.SEARCH_PLAIN
                    else cls.MSG_ENTER_REGEX,
                    type_of_msg=Output.INTERACTION,
                )
                what = UserInput.readline()
                Output.separate(Output.INTERACTION)
                if not what:
                    Output.report_action_cancelled()
                    return False

            cls._find_what = what

            try:
                _flags = (efabregex.get_default_flags() & ~re.IGNORECASE) \
                         | (re.IGNORECASE if cs == cls.SEARCH_CI else 0)
                cls._find_re = re.compile(
                    re.escape(cls._find_what)
                    if mode == cls.SEARCH_PLAIN
                    else cls._find_what,
                    flags=_flags,
                )
                return cls._find_next(0)
            except re.error as e:
                Output.report_error(e)
                Output.say(
                    _("The search was cancelled because the pattern was "
                      "wrong"),
                    type_of_msg=Output.INFO,
                )
                return False

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def find_next(cls):
        return cls._find_next(Player.line_number() + 1)

    FOUND = _("A match was found for the search expression (%s) at line %s.")
    FOUND_SAME = _(
        "A match was found for the search expression (%s) at the current line "
        "(%s)."
    )
    NOT_FOUND = _("A match was not found for the search expression (%s).")

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _find_next(cls, where_from):
        if not cls._find_re:
            return False

        for i in range(where_from, len(Player.lines())):
            if cls._find_re.search(Player.lines()[i]):
                if i == Player.line_number():
                    Output.say(
                        cls.FOUND_SAME % (cls._find_what, i + 1),
                        type_of_msg=Output.INFO,
                    )
                else:
                    Output.say(
                        cls.FOUND % (cls._find_what, i + 1),
                        type_of_msg=Output.INFO
                    )
                Player.line_number(i)
                return True
        Output.say(cls.NOT_FOUND % cls._find_what, type_of_msg=Output.INFO)
        return False

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def find_previous(cls):
        if not cls._find_re:
            return False

        for i in range(Player.line_number() - 1, -1, -1):
            if cls._find_re.search(Player.lines()[i]):
                if i == Player.line_number():
                    Output.say(
                        cls.FOUND_SAME % (cls._find_what, i + 1),
                        type_of_msg=Output.INFO,
                    )
                else:
                    Output.say(
                        cls.FOUND % (cls._find_what, i + 1),
                        type_of_msg=Output.INFO
                    )
                Player.line_number(i)
                return True
        Output.say(cls.NOT_FOUND % cls._find_what, type_of_msg=Output.INFO)
        return False

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def go_random():
        Output.say(_("Choosing a random line."), type_of_msg=Output.INFO)
        Player.line_number(SEQUENCE_RANDOM.next())
        return True

    @classmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def go_modified(cls, forward=True):
        modified_lines = TrackingController.modified_lines()
        if not modified_lines:
            Output.say(SEQUENCE_MODIFIED.msg_empty, type_of_msg=Output.INFO)
            return False
        if forward:
            if SEQUENCE_MODIFIED.eof():
                if Player.line_number() == modified_lines[-1]:
                    Output.say(
                      SEQUENCE_MODIFIED.msg_eof,
                      type_of_msg=Output.INFO
                    )
                else:
                    Output.say(
                        _("There are no modified lines after this one."),
                        type_of_msg=Output.INFO,
                    )
                return False
            else:
                Output.say(
                    _("Skipping to the next modified line."),
                    type_of_msg=Output.INFO
                )
                Player.line_number(SEQUENCE_MODIFIED.next())
                return True
        else:
            if SEQUENCE_MODIFIED.bof():
                if Player.line_number() == modified_lines[0]:
                    Output.say(
                        SEQUENCE_MODIFIED.msg_bof,
                        type_of_msg=Output.INFO
                    )
                else:
                    Output.say(
                        _("There are no modified lines before this one."),
                        type_of_msg=Output.INFO,
                    )
                return False
            else:
                Output.say(
                    _("Skipping to the previous modified line."),
                    type_of_msg=Output.INFO,
                )
                Player.line_number(SEQUENCE_MODIFIED.previous())
                return True

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def change_speed(delta):
        with EspeakController.get_lock():
            speed = EspeakController.speed()
            if speed >= MAXSPEED and delta > 0:
                Output.say(
                    _("Already at maximum speed"),
                    type_of_msg=Output.INFO
                )
                return False
            elif speed <= MINSPEED and delta < 0:
                Output.say(
                    _("Already at minimum speed"),
                    type_of_msg=Output.INFO
                )
                return False
            speed += delta
            Output.say(
                _("%s words/minute") % speed,
                type_of_msg=Output.INFO
            )
            EspeakController.speed(speed)
        return True

    @staticmethod  # class PlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def cycle_line_number_printing():
        if not RuntimeOptions.show_line_number():
            RuntimeOptions.show_line_number(True)
            RuntimeOptions.show_total_lines(False)
        elif not RuntimeOptions.show_total_lines():
            RuntimeOptions.show_total_lines(True)
        else:
            RuntimeOptions.show_line_number(False)
            RuntimeOptions.show_total_lines(False)


@staticclass
class NonPlayerCommands:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    @classmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def run_in_shell(cls, cmd=None):
        if Main.scripted_mode:
            return

        if not cmd:
            cls.open_shell()
        else:
            with Output.get_lock():
                subprocess.run(
                    cmd,
                    shell=True,
                    stdout=Output.get_file(Output.NORMAL),
                    stderr=Output.get_file(Output.NORMAL),
                )
                Output.separate(Output.NORMAL)

    @staticmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def open_shell():
        if Main.scripted_mode:
            return

        with Output.get_lock():
            Output.say(
                _("Entering the shell; close the shell to return to the "
                  "program."),
                type_of_msg=Output.INFO,
            )
            UserInput.set_normal()
            ret = True
            try:
                subprocess.call(os.environ["COMSPEC" if WINDOWS else "SHELL"])
                print()
                Output.say(_("Resuming the program."), type_of_msg=Output.INFO)
            except Exception as e:
                ret = False
                Output.report_error(e)
                Output.say(
                    _("The program could not open a shell."),
                    type_of_msg=Output.ERROR
                )
            return ret

    @classmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def open_file(cls, name):
        if not os.path.exists(name):
            Output.say(
                _("The file/directory %s does not exist.") % name,
                type_of_msg=Output.ERROR,
            )
            return False
        else:
            Main.start_daemon(lambda: cls._open_file(name))
            return True

    @staticmethod  # class NonPlayerCommands
    def _open_file(name):
        try:
            if not os.path.exists(name):
                raise Exception(_("Cannot find file/directory: %s.") % name)
            Output.say(
                _("Opening %s in another window.") % name,
                type_of_msg=Output.INFO
            )
            # In case you modify the following call, be VERY careful to ensure
            # sanitization.
            if WINDOWS:
                subprocess.run(
                    ["start", name],
                    shell=True,
                    text=True,
                    capture_output=True,
                    check=True,
                )
            else:
                subprocess.run(
                    ["xdg-open", name],
                    text=True,
                    capture_output=True,
                    check=True
                )
        except Exception as e:
            with Output.get_lock():
                Output.report_error(e)
                Output.say(
                    _("The program could not open file: %s") % name,
                    type_of_msg=Output.ERROR,
                )

    @classmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def open_input_file(cls):
        input_file = InputTextLoader.input_file()
        if input_file is not None:
            return cls.open_file(input_file)
        Output.say(_("No input file was given."), type_of_msg=Output.ERROR)
        NonPlayerCommands.show_input_command()
        return False

    @classmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def choose_and_open_file(
        cls, file_list, no_file_msg=_("There are no files to edit.")
    ):

        if not file_list:
            Output.say(no_file_msg, type_of_msg=Output.ERROR)
            return False

        Player.stop()

        if len(file_list) == 1:
            return cls.open_file(file_list[0])

        with Output.get_lock():
            Output.say(
                _("Choose file to edit:"),
                type_of_msg=Output.INTERACTION
            )

            n = 1
            s = ""
            for f in file_list:
                s += str(n) + ": " + f + "\n"
                n += 1
            s += "\n"
            s += _("Press 0 to cancel")
            Output.say(
                s,
                type_of_msg=Output.INTERACTION,
                wrap=False,
                print_prompt=False
            )

            while True:
                c = UserInput.getch()
                if c.isdigit():
                    if c == "0":
                        Output.report_action_cancelled()
                        return False
                    elif int(c) >= 1 and int(c) <= len(file_list):
                        f = file_list[int(c) - 1]
                        return cls.open_file(f)

    @staticmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def show_input_command():
        Output.say(
            _("The input command is:\n\n%s") % InputTextLoader.input_command(),
            type_of_msg=Output.INFO,
        )

    _in_command_loop = False

    @classmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def command_loop(cls):
        if cls._in_command_loop:
            Output.say(
                _(
                    "The petition to enter the command loop was ignored "
                    "because you are already in the command loop."
                ),
                type_of_msg=Output.INFO,
            )
            return
        cls._in_command_loop = True
        msg = _("You have entered the command line mode.")
        msg += "\n" + _(
            "Here you can enter one or more commands in the internal "
            "scripting language."
        )
        msg += "\n" + _("Refer to the user manual for help on commands.")
        msg += "\n" + ("In command mode, some functionalities are suspended.")
        msg += " " + _("(For example, file monitoring and automatic line "
                       "advancing.)")
        msg += "\n" + _(
            "WARNING: this is an experimental feature, not intended for "
            "normal users."
        )
        msg += "\n" + _("Press <Enter> when finished.")
        with Output.get_lock():
            Output.say(msg, type_of_msg=Output.INFO_EXTENDED)
            while True:
                line = UserInput.readline(
                    prompt=Output.get_prompt(Output.INTERACTION)
                )
                Output.separate(Output.INTERACTION)
                if not line:
                    Output.say(
                        _("You are returning to the normal mode."),
                        type_of_msg=Output.INFO,
                    )
                    break
                parsed_command = Commands.parse(line.strip())
                if parsed_command:
                    Commands.process(parsed_command)
        cls._in_command_loop = False

    # No matter how wonderful this program is, the user will want to get out
    #  from it sooner or later.
    @staticmethod  # class NonPlayerCommands
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def quit(ask_for_confirmation=True):
        if (
            ask_for_confirmation
            and not RuntimeOptions.quit_without_prompt()
            and not Main.scripted_mode
        ):
            with Output.get_lock():
                if not UserInput.confirm_action(
                    _("Do you really want to quit?")
                ):
                    return False
        Main.terminate()


@staticclass
class SpokenFeedback:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    NO_FEEDBACK = 0
    MINIMUM_FEEDBACK = 1
    FULL_FEEDBACK = 2

    _message_levels = {
        "restarting": MINIMUM_FEEDBACK,
        "starting-again": MINIMUM_FEEDBACK,
        "jumping-back": MINIMUM_FEEDBACK,
        "jumping-forward": MINIMUM_FEEDBACK,
        "continuing": MINIMUM_FEEDBACK,
        "subst-changed": MINIMUM_FEEDBACK,
        "reload-delayed": FULL_FEEDBACK,
        "no-changes": FULL_FEEDBACK,
        "changes-reverted": FULL_FEEDBACK,
        "many-changes": FULL_FEEDBACK,
        "changes-after": FULL_FEEDBACK,
        "changes-here": FULL_FEEDBACK,
        "changes-next": FULL_FEEDBACK,
        "changes-before": FULL_FEEDBACK,
        "file-increased": FULL_FEEDBACK,
        "file-decreased": FULL_FEEDBACK,
        "file-too-short": FULL_FEEDBACK,
        "file-is-empty": FULL_FEEDBACK,
        "file-changed-again": FULL_FEEDBACK,
        "blank-areas-changed": FULL_FEEDBACK,
    }

    _messages = {}

    @classmethod  # class SpokenFeedback
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def keys(cls):
        return cls._message_levels.keys()

    @classmethod  # class SpokenFeedback
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def set_message(cls, key, value):
        cls._messages[key] = value

    @classmethod  # class SpokenFeedback
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def append_message(cls, message_list, key):
        msg = cls.get_message(key)
        if msg:
            message_list.append(msg)
            return True
        return False

    @classmethod  # class SpokenFeedback
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def get_message(cls, key):
        if (
            key in cls._messages
            and cls._message_levels[key] <= RuntimeOptions.feedback_mode()
        ):
            return cls._messages[key]
        return None


@staticclass
class InputTextLoader:

    _lock = threading.RLock()

    Main.register_termination_hook(lambda: InputTextLoader._stop())

    _input_file = None  # File to be read
    _input_command = None  # Command to get the text content of the input_file
    _input_pipeline = None

    _transformation_rule_files = []
    _transformation_log_command = None
    _transformation_log_pipeline = None

    _segmenting_regex = None
    _separator_regex = None
    _separator_string = None

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def input_file(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._input_file
            cls._input_file = value

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def input_command(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._input_command
            cls._input_command = value
            # TODO perhaps some sanitization should be done here
            # _input_command was already sanitized by
            #  CmdLineArgs._get_input_source(), except for --do and
            # --preprocess. We convert it into a series of separate commands,
            # so we can check the exit status of each one.
            try:
                cls._input_pipeline = cls._create_input_pipeline(
                    cls._input_command
                )
            except ValueError as e:
                Main.terminate(
                    _("A wrong input command was given: %s. Reported error "
                      "is: %s.")
                    % (value, e)
                )

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _create_input_pipeline(cls, cmd):
        if isinstance(cmd, str):
            return cls._create_input_pipeline(shlex.split(cmd))
        elif "|" in cmd:
            n = cmd.index("|")
            return [cmd[0:n]] + cls._create_input_pipeline(cmd[n+1:])
        return [cmd]

    @classmethod  # class InputTextLoader
    def segmenting_regex(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._segmenting_regex
            cls._segmenting_regex = value

    @classmethod  # class InputTextLoader
    def separator_regex(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._separator_regex
            cls._separator_regex = value

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def separator_string(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._separator_string
            cls._separator_string = value

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def transformation_rule_files(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._transformation_rule_files
            cls._transformation_rule_files = value

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def transformation_log_command(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._transformation_log_command
            cls._transformation_log_command = value

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def log_transformation_rules(cls):
        with cls._lock:
            if not cls._transformation_log_command:
                Output.say(
                    _(
                        "Cannot show the effect of transformation rules "
                        "because none were given."
                    ),
                    type_of_msg=Output.ERROR,
                )
                return
            if not cls._transformation_log_pipeline:
                # _transformation_log_command was already sanitized by
                # CmdLineArgs._get_transformation_rules().
                cls._transformation_log_pipeline = cls._create_input_pipeline(
                    cls._transformation_log_command
                )
            try:
                Output.say(
                    _("Preparing the transformation-rules log."),
                    type_of_msg=Output.INFO,
                )
                text = None
                # _transformation_log_pipeline should be already sanitized (see
                # above). Be VERY careful to ensure sanitization if you were to
                # modify the following code or the code in CmdLineArgs on which
                # it depends.
                for cmd in cls._transformation_log_pipeline:
                    cp = subprocess.run(
                        cmd,
                        input=text,
                        text=True,
                        check=True,
                        capture_output=True
                    )
                    text = cp.stdout
                log = cp.stderr
                if len(log) > 0:
                    Player.stop()
                    if Main.scripted_mode:
                        log += "END OF LOG"
                        Output.say(log, type_of_msg=Output.NORMAL_EXTENDED)
                    else:
                        Output.pager(
                            log,
                            title=_("Showing the transformation-rules log.")
                        )
                else:
                    Output.say(
                        _(
                            "It seems the text source was not affected by the "
                            "transformation rules."
                        ),
                        type_of_msg=Output.INFO,
                    )
            except Exception as e:
                with Output.get_lock():
                    Output.report_error(e)
                    Output.say(
                        _("The program cannot show the transformation-rules "
                          "log."),
                        type_of_msg=Output.ERROR,
                    )

    _running = False
    _stopped = threading.Condition(_lock)

    _subprocess = None

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def start(cls):
        with cls._lock:
            cls._stop()  # Just in case
            cls._running = True
            Main.start_daemon(cls._run)

    @classmethod  # class InputTextLoader
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _stop(cls):
        with cls._lock:
            if not cls._running:
                return
            cls._running = False
            if cls._subprocess is not None and cls._subprocess.poll() is None:
                cls._subprocess.terminate()
            cls._stopped.wait()

    CANNOT_FIND_FILE = _("The program cannot find the input file: %s")
    ERROR_GETTING_INPUT = _(
        "An error has occurred while trying to read the text source."
    )
    NO_READABLE_TEXT = _("The text source is empty or contains no readable "
                         "text.")
    NO_READABLE_SEGMENTS = _("No readable segments were found.")

    @classmethod  # class InputTextLoader
    def _run(cls):
        with cls._lock:
            if cls._input_file is not None:
                if not os.path.isfile(cls._input_file):
                    Output.say(
                        cls.CANNOT_FIND_FILE % cls._input_file,
                        type_of_msg=Output.INFO
                    )
                    Main.event(Main.TEXT_LOADING_ERROR)
                    cls._running = False
                    cls._stopped.notify()
                    return
                else:
                    Output.say(
                        _("Reading file: %s ...") % cls._input_file,
                        type_of_msg=Output.INFO,
                    )
            else:
                Output.say(
                    _("Reading output from: %s") % cls._input_command,
                    type_of_msg=Output.INFO,
                )
            try:
                text = None
                # _input_pipeline should be already sanitized (see
                # InputTextLoader.input_command()).
                for cmd in cls._input_pipeline:
                    cls._lock.release()
                    process = subprocess.Popen(
                        cmd,
                        encoding=INPUT_ENCODING_SIG,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    cls._lock.acquire()
                    cls._subprocess = process
                    cls._lock.release()
                    text, errors = process.communicate(text)
                    cls._lock.acquire()
                    if not cls._running:
                        cls._stopped.notify()
                        return
                    if errors:
                        with Output.get_lock():
                            Output.report_error(errors.strip())
                            Output.say(
                                cls.ERROR_GETTING_INPUT,
                                type_of_msg=Output.ERROR
                            )
                        Main.event(Main.TEXT_LOADING_ERROR)
                        cls._running = False
                        cls._stopped.notify()
                        return
            except Exception as e:
                with Output.get_lock():
                    Output.report_error(e)
                    Output.say(
                        cls.ERROR_GETTING_INPUT,
                        type_of_msg=Output.ERROR
                    )
                Main.event(Main.TEXT_LOADING_ERROR)
                cls._lock.acquire()
                cls._running = False
                cls._stopped.notify()
                return
            cls._split_text_and_create_event(text)
            cls._running = False
            cls._stopped.notify()

    @classmethod  # class InputTextLoader
    def _split_text_and_create_event(cls, text):
        if not text.strip():
            Output.say(cls.NO_READABLE_TEXT, type_of_msg=Output.ERROR)
            Main.event(Main.TEXT_LOADING_ERROR)
            return
        else:
            lines = cls._split_text(text)
            lines = list(map(str.strip, lines))
            lines = [x for x in lines if x]
            if not lines:
                msg = cls.NO_READABLE_SEGMENTS
                if (
                    InputTextLoader.segmenting_regex()
                    or InputTextLoader.separator_regex()
                ):
                    msg += " " + _(
                        "Hint: perhaps the segmentation rule or "
                        "separator given in the command line is wrong."
                    )
                Output.say(msg, type_of_msg=Output.ERROR)
                Main.event(Main.TEXT_LOADING_ERROR)
                return
        Main.event(Main.TEXT_LOADING_SUCCESS, (text, lines))

    @classmethod  # class InputTextLoader
    def _split_text(cls, text):
        if cls._separator_string:
            return text.split(cls._separator_string)
        elif cls._separator_regex:
            return re.split(cls._separator_regex, text)
        elif cls._segmenting_regex:
            lines = re.findall(cls._segmenting_regex, text)
            if lines and isinstance(lines[0], tuple):
                lines = [x for sublist in lines for x in sublist]
            return lines
        else:
            return text.split("\n")


@staticclass
class FileMonitor:

    _lock = threading.RLock()

    _files = []
    _modification_times = None
    _actions = {}

    MONITORING_ERROR = _(
        "Error while trying to get modification time of file/directory: %s"
    )
    WRONG_MONITORED_TARGET = _(
        "%s is not a file nor a directory. Its modification time cannot be "
        "checked."
    )

    @classmethod  # class FileMonitor
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def files(cls):
        with cls._lock:
            return cls._files

    @classmethod  # class FileMonitor
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def register_group(cls, group, action):
        with cls._lock:
            cls._files.extend(group)
            cls._actions[tuple(group)] = action

    @classmethod  # class FileMonitor
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def initialize(cls):
        with cls._lock:
            cls._modification_times = {}
            for f in cls._files:
                try:
                    cls._modification_times[f] = os.path.getmtime(f)
                except IOError as e:
                    Output.say(
                        cls.MONITORING_ERROR % f,
                        type_of_msg=Output.ERROR
                    )
                    Main.terminate(Main.REPORTED_ERROR_MSG % e)

    _running = False

    @classmethod  # class FileMonitor
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def start(cls):
        with cls._lock:
            if cls._running:
                return
            cls._running = True
            Main.start_daemon(cls._run)

    _monitoring_interval = 2

    @classmethod  # class FileMonitor
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def monitoring_interval(cls, value=None):
        with cls._lock:
            if value is None:
                return cls._monitoring_interval
            cls._monitoring_interval = max(value, 1)

    @classmethod  # class FileMonitor
    def _run(cls):
        with cls._lock:
            interval = cls._monitoring_interval
        while True:
            n = 0
            while n < interval:
                time.sleep(1)
                n += 1
                with cls._lock:
                    interval = cls._monitoring_interval
            cls.check_files(called_from_inside=True)

    @classmethod  # class FileMonitor
    def check_files(cls, say_it=False, called_from_inside=False):
        if not called_from_inside:
            Main.start_daemon(lambda: cls.check_files(called_from_inside=True))
            return
        with cls._lock:
            files_to_check = list(cls._actions.items())
        checking_msg_already_printed = False
        no_changes_msg_already_printed = False
        for group, action in files_to_check:
            change_detected = False
            for f in group:
                if not checking_msg_already_printed and say_it:
                    Output.say(
                        _(
                            "Checking modification times of monitored "
                            "files/directories."
                        ),
                        type_of_msg=Output.INFO,
                    )
                    checking_msg_already_printed = True
                if os.path.isfile(f) or os.path.isdir(f):
                    try:
                        mtime = os.path.getmtime(f)
                        if mtime != cls._modification_times[f]:
                            cls._modification_times[f] = mtime
                            Output.say(
                                _("Modification time changed: %s (%s).")
                                % (
                                  f,
                                  time.strftime(
                                      "%X",
                                      time.localtime(mtime)
                                  )
                                ),
                                type_of_msg=Output.INFO,
                            )
                            change_detected = True
                    except IOError as e:
                        with Output.get_lock():
                            Output.say(
                                cls.MONITORING_ERROR % f,
                                type_of_msg=Output.ERROR
                            )
                            Output.report_error(e)
                            Main.terminate(Main.PROGRAM_MUST_TERMINATE_NOW)
                else:
                    Output.say(
                        cls.WRONG_MONITORED_TARGET % f,
                        type_of_msg=Output.ERROR
                    )
            if change_detected:
                action()
            elif say_it and not no_changes_msg_already_printed:
                Output.say(
                    _("No modification time changes were detected."),
                    type_of_msg=Output.INFO,
                )
                no_changes_msg_already_printed = True


@staticclass
class TrackingController:

    # Most of the state-accessing code of this class is called only from the
    # main thread. A lock is provided below for some critical sections of
    # multithreaded code.

    _feedback_player = EspeakController()
    Main.register_termination_hook(lambda: TrackingController.stop())

    NO_TRACKING = 0
    BACKWARD_TRACKING = 1
    FORWARD_TRACKING = 2
    RESTART_FROM_BEGINNING = 3

    _registered_text = None
    _registered_lines = None
    _registered_len = None

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def register(cls, text, lines):
        if cls._registered_text is None:
            cls._registered_text = text
            cls._registered_lines = lines
            cls._registered_len = len(lines)
        else:
            cls._report_changes_and_register(text, lines)

    _input_lines_changed = False
    _blank_areas_changed = False
    _newlen = None
    _modified_lines = []
    _spoken_feedback = []

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def modified_lines(cls):
        return cls._modified_lines

    _player_was_at_line = None
    _player_was_at_eol = False
    _restart_player_after_feedback = False
    _changed_again = False

    _new_line_number = None

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_changes_and_register(cls, text, lines):
        cls._player_was_at_line = Player.line_number()
        cls._player_was_at_eol = Player.at_eol()
        cls._restart_player_after_feedback |= Player.running_and_not_paused()

        cls._changed_again = cls.spoken_feedback_running()
        cls._compute_changes(text, lines)
        cls._new_line_number = cls._get_new_line_number()
        cls._compose_spoken_feedback()
        cls._show_changes()

        if cls._spoken_feedback:
            Player.stop()
            cls._play_feedback_and_register(text, lines)
        else:
            while cls.spoken_feedback_running():  # Just in case
                time.sleep(0.1)
            cls._update_player_and_register(text, lines)

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _compute_changes(cls, text, lines):
        cls._blank_areas_changed = cls._compare_blank_areas(
            text,
            cls._registered_text
        )
        cls._newlen = len(lines)
        cls._modified_lines = cls._compare_lines(lines, cls._registered_lines)

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _compare_blank_areas(cls, text, old_text):
        old_blank_areas = re.findall(r"(\s+?)\n+", old_text)
        blank_areas = re.findall(r"(\s+?)\n+", text)
        return old_blank_areas != blank_areas

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _compare_lines(cls, lines, old_lines):
        if not lines:
            return []
        s = difflib.SequenceMatcher(None, lines, old_lines, autojunk=False)
        tmp = [x for x in s.get_opcodes() if x[0] != "equal"]
        cls._input_lines_changed = len(tmp) > 0
        modified_lines = []
        for x in tmp:
            if x[0] == "insert":
                modified_lines.extend(range(x[1], x[1] + 1))
            else:
                modified_lines.extend(range(x[1], x[2]))
        if cls._newlen < cls._registered_len:
            modified_lines = [n for n in modified_lines if n < cls._newlen]
        if RuntimeOptions.sequence_mode() is SEQUENCE_MODIFIED:
            # cls._modified_lines still contains the list of modified
            # lines from the previous text's version.
            tmp_modified_lines = [
                x
                for x in cls._modified_lines
                if x > cls._player_was_at_line and x < cls._newlen
            ]
            if tmp_modified_lines:
                modified_lines = sorted(list(set(
                            modified_lines + tmp_modified_lines
                )))
        return modified_lines

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _show_changes(cls):
        with Output.get_lock():
            cls._report_changed_again()
            if cls._newlen == 0:
                Output.say(
                    _("The input file is empty."),
                    type_of_msg=Output.INFO
                )
                return
            cls._report_blank_areas_changed()
            cls._report_length_change()
            if not cls._modified_lines:
                if cls._newlen == cls._registered_len:
                    cls._report_no_modified_lines()
                    return
            else:
                cls._show_modified_lines_and_action()

            if RuntimeOptions.tracking_mode() == cls.RESTART_FROM_BEGINNING:
                Output.say(
                    _("Restarting from the beginning."),
                    type_of_msg=Output.INFO
                )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_changed_again(cls):
        if cls._changed_again:
            Output.say(
                _("The input file changed again on disk."),
                type_of_msg=Output.INFO
            )
            Output.say(
                _("Reporting changes again (may include previously reported "
                  "changes)."),
                type_of_msg=Output.INFO,
            )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_blank_areas_changed(cls):
        if cls._blank_areas_changed:
            Output.say(
                _("Blank areas of the input file have changed."),
                type_of_msg=Output.INFO,
            )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_length_change(cls):
        if cls._newlen < cls._registered_len:
            Output.say(
                _("The text was shortened from %s to %s line(s).")
                % (cls._registered_len, cls._newlen),
                type_of_msg=Output.INFO,
            )
            if cls._newlen <= cls._player_was_at_line:
                Output.say(
                    _("The text was shortened before the current line. "
                      "Repositioning."),
                    type_of_msg=Output.INFO,
                )
        elif cls._newlen > cls._registered_len:
            Output.say(
                _("The text was extended from %s to %s lines.")
                % (cls._registered_len, cls._newlen),
                type_of_msg=Output.INFO,
            )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_no_modified_lines(cls):
        if not cls._changed_again:
            Output.say(
                _("No changes to the text were detected."),
                type_of_msg=Output.INFO
            )
        else:
            Output.say(
                _("The latest changes have been reverted."),
                type_of_msg=Output.INFO
            )

    _ACTION_MSG_1 = _("Changes were detected at lines: %s (current line is: "
                      "%s).")
    _ACTION_MSG_2 = _("Changes were detected at lines: %s; jumping back from "
                      "line %s.")
    _ACTION_MSG_3 = _("Changes were detected at lines: %s; restarting at line "
                      "%s.")
    _ACTION_MSG_4 = _("Changes were detected at lines: %s; continuing at line "
                      "%s.")
    _ACTION_MSG_5 = _("Changes were detected at lines: %s; jumping forward "
                      "from line %s.")

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _show_modified_lines_and_action(cls):
        changes = cls._get_modified_lines_representation()
        delta = 1
        msg = cls._ACTION_MSG_1
        if cls._new_line_number is not None:
            if RuntimeOptions.tracking_mode() == cls.RESTART_FROM_BEGINNING:
                pass
            elif cls._modified_lines[0] < cls._player_was_at_line:
                msg = cls._ACTION_MSG_2
            elif cls._modified_lines[0] == cls._player_was_at_line:
                msg = cls._ACTION_MSG_3
            elif (
                cls._player_was_at_eol
                and cls._modified_lines[0] == cls._player_was_at_line + 1
            ):
                msg = cls._ACTION_MSG_4
                delta = 2
            elif RuntimeOptions.tracking_mode() == cls.FORWARD_TRACKING:
                msg = cls._ACTION_MSG_5
        Output.say(
            msg % (changes, cls._player_was_at_line + delta),
            type_of_msg=Output.INFO
        )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_modified_lines_representation(cls):
        # Create a list of contiguous ranges:
        # [(start1, end1), (start2, end2), ...]
        first = cls._modified_lines[0]
        tmp = [(first, first)]
        last = first
        for line in cls._modified_lines[1:]:
            if line == last + 1:
                tmp[-1] = (first, line)
            else:
                first = line
                tmp.append((first, first))
            last = line
        # Add 1 to line numbers for printing:
        tmp = [(x[0] + 1, x[1] + 1) for x in tmp]
        # Stringify ranges:
        tmp = [str(x[0]) if x[0] == x[1] else "%s-%s" % x for x in tmp]
        return ", ".join(tmp)

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _compose_spoken_feedback(cls):
        cls._spoken_feedback = []
        if cls._changed_again:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "file-changed-again"
            )
        if cls._newlen == 0:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "file-is-empty"
            )
            return
        if cls._blank_areas_changed:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "blank-areas-changed"
            )
        cls._feedback_for_length_change()
        if not cls._modified_lines:
            cls._feedback_when_no_modified_lines()
        else:
            cls._feedback_when_modified_lines()
        cls._feedback_for_action_taken()

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _feedback_for_length_change(cls):
        if cls._newlen < cls._registered_len:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "file-decreased"
            )
            if cls._newlen <= cls._player_was_at_line:
                SpokenFeedback.append_message(
                    cls._spoken_feedback,
                    "file-too-short"
                )
        elif cls._newlen > cls._registered_len:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "file-increased"
            )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _feedback_when_no_modified_lines(cls):
        if cls._newlen == cls._registered_len:
            if not cls._changed_again:
                SpokenFeedback.append_message(
                    cls._spoken_feedback,
                    "no-changes"
                )
            else:
                SpokenFeedback.append_message(
                    cls._spoken_feedback,
                    "changes-reverted"
                )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _feedback_when_modified_lines(cls):
        if cls._modified_lines[0] < cls._player_was_at_line:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "changes-before"
            )
        elif cls._modified_lines[0] == cls._player_was_at_line:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "changes-here"
            )
        elif (
            cls._player_was_at_eol
            and cls._modified_lines[0] == cls._player_was_at_line + 1
        ):
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "changes-next"
            )
        else:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "changes-after"
            )
        if len(cls._modified_lines) > 1:
            SpokenFeedback.append_message(cls._spoken_feedback, "many-changes")

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _feedback_for_action_taken(cls):
        if (
            RuntimeOptions.tracking_mode() == cls.RESTART_FROM_BEGINNING
            and cls._new_line_number is not None
        ):
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "starting-again"
            )
        elif (
            RuntimeOptions.sequence_mode() is SEQUENCE_MODIFIED
            and Player.never_said_anything()
        ):
            pass
        elif cls._new_line_number is None:
            if cls._spoken_feedback and cls._restart_player_after_feedback:
                SpokenFeedback.append_message(
                    cls._spoken_feedback,
                    "restarting"
                )
        elif (
            Player.running_and_not_paused()
            or cls._changed_again
            or RuntimeOptions.restarting_message_when_not_playing()
        ):
            cls._feedback_when_player_will_restart()

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _feedback_when_player_will_restart(cls):
        if cls._new_line_number < cls._player_was_at_line:
            SpokenFeedback.append_message(cls._spoken_feedback, "jumping-back")
        elif cls._new_line_number == cls._player_was_at_line:
            SpokenFeedback.append_message(cls._spoken_feedback, "restarting")
        elif (
            cls._new_line_number == cls._player_was_at_line + 1
            and cls._player_was_at_eol
        ):
            SpokenFeedback.append_message(cls._spoken_feedback, "continuing")
        elif (
            RuntimeOptions.sequence_mode() is SEQUENCE_MODIFIED
            and cls._new_line_number == cls._player_was_at_line + 1
            and cls._new_line_number == cls._modified_lines[0]
        ):
            SpokenFeedback.append_message(cls._spoken_feedback, "continuing")
        elif RuntimeOptions.tracking_mode() == cls.FORWARD_TRACKING:
            SpokenFeedback.append_message(
                cls._spoken_feedback,
                "jumping-forward"
            )
        else:
            SpokenFeedback.append_message(cls._spoken_feedback, "restarting")

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_new_line_number(cls):
        modified_lines = cls._modified_lines
        if RuntimeOptions.tracking_mode() == cls.NO_TRACKING:
            return None
        elif RuntimeOptions.tracking_mode() == cls.RESTART_FROM_BEGINNING:
            return (
                0
                if modified_lines or RuntimeOptions.restart_on_touch()
                else None
            )
        elif not modified_lines:
            return cls._new_line_number_when_no_modified_lines()
        elif RuntimeOptions.tracking_mode() == cls.FORWARD_TRACKING:
            return cls._new_line_number_for_forward_tracking()
        else:
            line_number = cls._player_was_at_line\
                          + (1 if cls._player_was_at_eol else 0)
            if modified_lines[0] <= line_number:
                return modified_lines[0]
        return None

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _new_line_number_when_no_modified_lines(cls):
        if cls._changed_again and cls._newlen == cls._registered_len:
            return Player.line_number()
        elif RuntimeOptions.tracking_mode() == cls.FORWARD_TRACKING:
            return (
                None
                if cls._newlen <= cls._registered_len
                else cls._registered_len
            )
        else:
            return None

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _new_line_number_for_forward_tracking(cls):
        if (
            RuntimeOptions.sequence_mode() is SEQUENCE_MODIFIED
            and cls._modified_lines[0] > cls._player_was_at_line
            and Player.running_and_not_paused()
        ):
            return None
        else:
            return cls._modified_lines[0]

    _lock = threading.RLock()

    _running = False
    _stopped = threading.Condition(_lock)
    _stopped_from_inside = False

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _play_feedback_and_register(cls, text, lines):
        with cls._lock:
            if cls._running:
                cls._stopped_from_inside = True
                cls.stop()
                cls._stopped_from_inside = False
            cls._running = True
        Main.start_daemon(lambda: cls._run(text, lines))

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def spoken_feedback_running(cls):
        with cls._lock:
            return cls._running

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def stop_playing_feedback(cls):  # Provided just as a convenience.
        cls.stop()

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def stop(cls):
        with cls._lock:
            if not cls._running:
                return
            cls._running = False
            if cls._feedback_player.running():
                cls._feedback_player.stop()
            cls._stopped.wait()

    @classmethod  # class TrackingController
    def _run(cls, text, lines):
        with cls._lock:
            for line in cls._spoken_feedback:
                try:
                    cls._feedback_player.say(line, on_start=cls._lock.release)
                    cls._lock.acquire()
                    if not cls._running:
                        break
                except EspeakControllerError as e:
                    cls._lock.acquire()
                    with Output.get_lock():
                        Output.say(
                            _("There was an error while reading spoken "
                              "feedback."),
                            type_of_msg=Output.ERROR,
                        )
                        Output.report_error(e)
                        Output.say(
                            _("The reading is stopped, you can try to restart "
                              "it."),
                            type_of_msg=Output.INFO,
                        )
                    cls._running = False
                    return
            cls._running = False
            cls._stopped.notify()
            if cls._stopped_from_inside:
                return
            Main.event(
                Main.SPOKEN_FEEDBACK_ENDED,
                lambda: cls._update_player_and_register(text, lines),
            )

    @classmethod  # class TrackingController
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _update_player_and_register(cls, text, lines):
        n = cls._new_line_number
        if n is not None:
            Player.stop()
            Player.line_number(n)
        elif Player.refresh_current_line():
            Player.stop()
        a = cls._restart_player_after_feedback and cls._spoken_feedback
        b = n is not None and RuntimeOptions.restart_after_change()
        c = RuntimeOptions.restart_on_touch() and not Player.running()
        if a or b or c:
            Player.start()
        cls._restart_player_after_feedback = False
        cls._registered_text = text
        cls._registered_lines = lines
        cls._registered_len = len(lines)


@staticclass
class UserInput:

    # This class does not implement a lock, as all of its methods MUST only be
    # called from the main thread.

    _old_tty_settings = None

    if LINUX:
        signal.signal(
            signal.SIGCONT,
            lambda signum, frame: UserInput.set_normal()
        )
    Main.register_termination_hook(lambda: UserInput.set_normal())

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def set_raw(cls):
        if WINDOWS:
            return
        elif not LINUX:
            traceback.print_stack()
            Main.terminate(UNSUPPORTED_PLATFORM)
        if cls._old_tty_settings is None:
            fd = sys.stdin.fileno()
            cls._old_tty_settings = termios.tcgetattr(fd)
            new_tty_settings = termios.tcgetattr(fd)
            new_tty_settings[0] &= ~termios.IXON
            new_tty_settings[3] &= ~(
                termios.ISIG | termios.ICANON | termios.ECHO
            )
            termios.tcsetattr(fd, termios.TCSANOW, new_tty_settings)

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def set_normal(cls):
        if WINDOWS:
            return
        elif not LINUX:
            traceback.print_stack()
            Main.terminate(UNSUPPORTED_PLATFORM)
        if cls._old_tty_settings is not None:
            termios.tcsetattr(
                sys.stdin.fileno(), termios.TCSANOW, cls._old_tty_settings
            )
            cls._old_tty_settings = None

    _A_LARGE_ENOUGH_NUMBER = 42

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def getch(cls, timeout=0):
        cls.set_raw()
        try:
            if timeout and not cls._input_available(timeout):
                return None
            if LINUX:
                return str(
                    os.read(sys.stdin.fileno(), cls._A_LARGE_ENOUGH_NUMBER),
                    encoding=SYSTEM_ENCODING,
                )
            elif WINDOWS:
                return str(msvcrt.getch(), encoding=SYSTEM_ENCODING)
            else:
                traceback.print_stack()
                Main.terminate(UNSUPPORTED_PLATFORM)
        except (KeyboardInterrupt, EOFError, OSError):
            return None

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def readline(cls, timeout=0, prompt=None):
        cls.set_normal()
        try:
            if timeout and not cls._input_available(timeout):
                return None
            if prompt is None:
                return input()
            return input(prompt)
        except (KeyboardInterrupt, EOFError, OSError):
            return None

    @staticmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _input_available(timeout):
        if LINUX:
            return select.select([sys.stdin], [], [], timeout)[0]
        elif WINDOWS:
            return msvcrt.kbhit()
        else:
            traceback.print_stack()
            Main.terminate(UNSUPPORTED_PLATFORM)

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def get_int(cls):
        with Output.get_lock():
            reply = cls.readline().strip()
            Output.separate(Output.INTERACTION)
            if not reply:
                Output.report_action_cancelled()
                return
            if reply.isdigit():
                return int(reply)
            else:
                Output.say(
                    _("You must enter a positive integer."),
                    type_of_msg=Output.ERROR
                )
                Output.report_action_cancelled()
                return None

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def choose_mode(cls, msg, options, current_mode_name, setter=None):
        with Output.get_lock():
            Output.say(msg, type_of_msg=Output.INTERACTION)
            n = 1
            s = ""
            names = list(options)
            for mode_name in names:
                mark_current = "*" if mode_name == current_mode_name else ""
                s += str(n) + ": " + mode_name + mark_current + "\n"
                n += 1
            s += "\n"
            s += _("Press 0 to cancel")
            Output.say(
                s,
                type_of_msg=Output.INTERACTION,
                wrap=False,
                print_prompt=False
            )
            while True:
                if Main.scripted_mode:
                    c = cls.readline().strip()
                else:
                    c = cls.getch()
                if c.isdigit():
                    if c == "0":
                        Output.report_action_cancelled()
                        return None
                    elif int(c) >= 1 and int(c) <= len(options):
                        mode_name = names[int(c) - 1]
                        if setter:
                            setter(mode_name)
                        return mode_name

    @classmethod  # class UserInput
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def confirm_action(cls, msg):
        if Main.scripted_mode:
            return False
        with Output.get_lock():
            msg += " [%s/%s]" % (YES_KEY.lower(), NO_KEY.upper())
            Output.say(msg, type_of_msg=Output.INTERACTION, end=" ")
            answer = False
            while True:
                ch = cls.getch().lower()
                if ch in [NO_KEY.lower(), YES_KEY.lower()]:
                    Output.say(
                        ch,
                        type_of_msg=Output.INTERACTION,
                        print_prompt=False
                    )
                    answer = ch == YES_KEY
                    break
                elif ch in [chr(13), chr(10)]:
                    Output.say(
                        NO_KEY.lower(),
                        type_of_msg=Output.INTERACTION,
                        print_prompt=False,
                    )
                    break
            return answer


@staticclass
class SEQUENCE_NORMAL:

    msg_bof = _("This is the beginning of the text.")
    msg_eof = _("This is the end of the text.")
    msg_first = _("Jumping back to the beginning of the text.")
    msg_last = _("Jumping forward to the end of the text.")
    msg_empty = None

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def empty():
        return False

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def first():
        return 0

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def last():
        return len(Player.lines()) - 1

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def bof():
        return Player.line_number() == 0

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def eof():
        return Player.line_number() == len(Player.lines()) - 1

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def next():
        n = Player.line_number()
        last = len(Player.lines()) - 1
        return n + 1 if n < last else n

    @staticmethod  # class SEQUENCE_NORMAL
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def previous():
        n = Player.line_number()
        return n - 1 if n else 0


class SEQUENCE_MODIFIED:

    msg_bof = _("This is the first modified line.")
    msg_eof = _("This is the last modified line.")
    msg_first = _("Jumping back to the first modified line.")
    msg_last = _("Jumping forward to the last modified line.")
    msg_empty = _("There are no modified lines.")

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def empty():
        return len(TrackingController.modified_lines()) == 0

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def first():
        m = TrackingController.modified_lines()
        return m[0] if m else SEQUENCE_NORMAL.first()

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def last():
        m = TrackingController.modified_lines()
        return m[-1] if m else SEQUENCE_NORMAL.last()

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def bof():
        m = TrackingController.modified_lines()
        return not m or Player.line_number() <= m[0]

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def eof():
        m = TrackingController.modified_lines()
        return not m or Player.line_number() >= m[-1]

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def next():
        n = Player.line_number()
        tmp = [x for x in TrackingController.modified_lines() if x > n] + [n]
        return tmp[0]

    @staticmethod  # class SEQUENCE_MODIFIED
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def previous():
        n = Player.line_number()
        tmp = [n] + [x for x in TrackingController.modified_lines() if x < n]
        return tmp[-1]


class SEQUENCE_RANDOM:

    msg_bof = _("This is the beginning of the random reading history.")
    msg_eof = _("This is the end of the random reading history.")
    msg_first = _("Jumping back to the beginning of the random reading "
                  "history.")
    msg_last = _("Jumping forward to the end of the random reading history.")
    msg_empty = None

    _HISTORY_MAX_LENGTH = 10
    _history = []
    _index = 0

    @staticmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def empty():
        return False

    @classmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def first(cls):
        h = cls._history
        return h[0] if h else cls.next()

    @classmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def last(cls):
        h = cls._history
        return h[-1] if h else cls.next()

    @staticmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def bof():
        return False

    @staticmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def eof():
        return False

    @classmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def next(cls):
        h = cls._history
        if not h or cls._index == len(h) - 1:
            where = randint(0, len(Player.lines()) - 1)
            h.append(where)
            if len(h) > cls._HISTORY_MAX_LENGTH:
                del h[0]
            cls._index = len(h) - 1
        else:
            cls._index += 1
            where = h[cls._index]
        return where

    @classmethod  # class SEQUENCE_RANDOM
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def previous(cls):
        h = cls._history
        if not h or cls._index == 0:
            where = randint(0, len(Player.lines()) - 1)
            h.insert(0, where)
            if len(h) > cls._HISTORY_MAX_LENGTH:
                del h[-1]
        else:
            cls._index -= 1
            where = h[cls._index]
        return where


@staticclass
class KeyBindings:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    DEFAULT_BINDINGS = {
        "\x03": "<%s>" % MACRO_QUIT_NOW,
        "Q": "<%s>" % MACRO_QUIT_NOW,
        "q": "<%s>" % MACRO_QUIT_ASK,
        " ": "<toggle>",
        "a": "<restart>",
        "A": "<restart-and-stop>",
        "x": "<stop-and-reset-pointer>",
        "V": "<first-stop>",
        "v": "<first>",
        "M": "<last-stop>",
        "m": "<last>",
        "N": "<next-stop>",
        "n": "<next>",
        "B": "<stop-or-previous>",
        "b": "<previous>",
        ".": "<toggle-stop-after-current-line>",
        ",": "<toggle-stop-after-each-line>",
        "S": "<toggle-apply-subst>",
        "D": "<toggle-show-subst>",
        "u": "<log-subst>",
        "j": "<log-transform>",
        "l": "<cycle-line-number>",
        "w": "<show-line>",
        "f": "<search-plain-case-insensitive>",
        "F": "<search-plain-case-sensitive>",
        "r": "<search-regex-case-insensitive>",
        "R": "<search-regex-case-sensitive>",
        "/": "<search>",
        "t": "<find-next>",
        "T": "<find-next-stop>",
        "e": "<find-prev>",
        "E": "<find-prev-stop>",
        "g": "<go-line>",
        "<": "<prev-change>",
        ">": "<next-change>",
        "*": "<random>",
        "+": "<faster>",
        "-": "<slower>",
        "o": "<open-input-file>",
        "O": "<open-input-file-stop>",
        "s": "<open-subst>",
        ":": "<open-transform>",
        "_": "<open-cl-monitored-file>",
        "c": "<open-shell>",
        "L": "<reload>",
        "C": "<check-files>",
        "?": "<choose-tracking-mode>",
        ")": "<choose-sequence-mode>",
        "=": "<choose-feedback-mode>",
        "0": "<special-mode>",
        "1": "<normal-mode>",
        "I": "<show-input-cmd-stop>",
        "i": "<show-input-cmd>",
    }

    _bindings = DEFAULT_BINDINGS
    _parsed_bindings = {}
    _key_bindings_to_quit = {}

    @classmethod  # class KeyBindings
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def set(cls, key_bindings):
        cls._bindings = key_bindings
        cls._parsed_bindings = {}

    @classmethod  # class KeyBindings
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def get_parsed_command(cls, ch):
        if ch not in cls._parsed_bindings:
            if ch in cls._bindings:
                parsed_command = Commands.parse(cls._bindings[ch])
                if parsed_command:
                    cls._parsed_bindings[ch] = parsed_command
                    return parsed_command
                return None
            return None
        return cls._parsed_bindings[ch]

    @classmethod  # class KeyBindings
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def is_bound_to_quit_command(cls, ch):
        if ch not in cls._key_bindings_to_quit:
            parsed_command = cls.get_parsed_command(ch)
            if not parsed_command:
                return False
            cls._key_bindings_to_quit[ch] = Commands.contains_quit(
                parsed_command
            )
        return cls._key_bindings_to_quit[ch]


@staticclass
class Substitutions:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    _rule_files = []

    @classmethod  # class Substitutions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def rule_files(cls, value=None):
        if value is None:
            return cls._rule_files
        cls._rule_files = value

    _rules = []
    _hist = []
    _loaded = False

    @classmethod  # class Substitutions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def load(cls, force=False):
        if cls._loaded and not force:
            return
        cls._rules = []
        for filename in cls._rule_files:
            try:
                with open(filename, "r", encoding=CONFIG_ENCODING) as f:
                    content = f.read()
                    # This will be removed if and when I implement protection
                    # rules directly within efabrules. (Currently, protection
                    # rules are implemented within efabtrans.)
                    m = re.search(
                        r"^\s*(\[[^[].*\])\s*$",
                        content,
                        flags=re.MULTILINE
                    )
                    if m:
                        raise Exception(
                            _(
                                "Substitution rules cannot contain sections "
                                "in this version: %s."
                            )
                            % m.group(1)
                        )
            except Exception as e:
                with Output.get_lock():
                    Output.report_error(e)
                    Output.say(
                        _(
                            "An error has occurred while trying to read "
                            "substitution rules file: %s."
                        )
                        % filename,
                        type_of_msg=Output.ERROR,
                    )
                    Output.say(
                        _("The substitution file (%s) will not be applied.")
                        % filename,
                        type_of_msg=Output.INFO,
                    )
                continue
            efabrules.process_rules(filename, content, cls._rules)
        cls._loaded = True

    @classmethod  # class Substitutions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def reload(cls):
        Output.say(
            _("New substitutions were loaded."),
            type_of_msg=Output.INFO
        )
        cls.load(force=True)
        Main.event(Main.NEW_SUBSTITUTIONS_LOADED)

    @classmethod  # class Substitutions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def apply(cls, line):
        # Initialize the substitution history with the original line
        cls._hist = [{"rule": None, "result": line}]

        for rule in cls._rules:
            line_bak = line
            try:
                line = efabrules.sub(rule, line)
            except efabrules.error as e:
                Output.report_error(e)

            if line_bak != line:
                cls._hist.append({"rule": rule, "result": line})

        return line

    @classmethod  # class Substitutions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def show_log(cls):
        if not cls._rules:
            Output.say(
                _(
                    "Cannot show the effect of substitution rules because "
                    "none were given."
                ),
                type_of_msg=Output.INFO,
            )
            return
        if not RuntimeOptions.apply_subst():
            Output.say(
                _("Substitution rules are not being applied."),
                type_of_msg=Output.INFO
            )
            return
        if len(cls._hist) == 1:
            Output.say(
                _("No substitutions were applied to this line."),
                type_of_msg=Output.INFO,
            )
            return
        s = ""
        for substitution in cls._hist:
            if substitution["rule"] is not None:
                s += substitution["rule"].filename + "\n"
                s += substitution["rule"].definition + "\n"
            s += substitution["result"]
            s += "\n\n"
        Player.stop()
        if Main.scripted_mode:
            s += "END OF LOG"
            Output.say(s, type_of_msg=Output.NORMAL_EXTENDED)
        else:
            try:
                Output.pager(
                    s,
                    title=_("Showing the substitution history."),
                    wrap=True
                )
            except Exception as e:
                with Output.get_lock():
                    Output.report_error(e)
                    Output.say(
                        _("The program cannot show the substitution history."),
                        type_of_msg=Output.ERROR,
                    )


@staticclass
class RuntimeOptions:

    # This class does not need a lock, because all of its methods are only
    # called from the main thread.

    # Validators for options that are currently being managed by RuntimeOptions
    # directly are defined here. When an option is managed by an instance of an
    # option class (see below), that instance will add a validator to this
    # dictionary.
    # TODO: if someday we convert 'static' classes into singleton objects,
    # option classes might implement the full descriptor protocol.
    _validators = {
        "apply-subst":
            lambda x: x in RuntimeOptions._BooleanOption._boolean_values,
        "show-subst":
            lambda x: x in RuntimeOptions._BooleanOption._boolean_values,
        "no-info":
            lambda x: x in RuntimeOptions._BooleanOption._boolean_values,
        "monitoring-interval":
            lambda x: x.isdigit(),
        "tracking-mode":
            lambda x: x in RuntimeOptions.TRACKING_OPTIONS,
        "sequence-mode":
            lambda x: x in RuntimeOptions.SEQUENCE_OPTIONS,
        "feedback-mode":
            lambda x: x in RuntimeOptions.FEEDBACK_OPTIONS,
    }

    _scripting_setters = {}

    class _BooleanOption:

        _true_values = ["true", "1"]
        _false_values = ["false", "0"]
        _boolean_values = _true_values + _false_values

        # class _BooleanOption
        def __init__(self, default, msg_when_true, msg_when_false):
            self._value = default
            self._msg_when_true = msg_when_true
            self._msg_when_false = msg_when_false

        # class _BooleanOption
        def __set_name__(self, owner, name):
            if not re.match(r"[a-z][a-z_]*[a-z]$", name):
                raise AttributeError(
                    "Internal error in RuntimeOptions: invalid option name %s."
                    % name
                )
            scripting_name = name.replace("_", "-")
            owner._validators[scripting_name] = (
                lambda x: x in self._true_values + self._false_values
            )
            owner._scripting_setters[scripting_name] = self._scripting_setter
            setattr(owner, name, staticmethod(self._public_accessor))

        # class _BooleanOption
        def _public_accessor(self, value=None, say_it=False):
            if value is None:
                return self._value
            self._value = value
            if say_it:
                msg = self._msg_when_true if value else self._msg_when_false
                if callable(msg):
                    msg = msg()
                Output.say(msg, type_of_msg=Output.INFO)

        # class _BooleanOption
        def _scripting_setter(self, value=None, say_it=False):
            old_value = self._value
            value = (
                (not old_value)
                if value is None
                else (value in self._true_values)
            )
            self._public_accessor(value, say_it)
            return old_value != value

    class _IntervalOption:

        # class _IntervalOption
        def __init__(self, default, msg):
            self._value = default
            self._msg = msg

        # class _IntervalOption
        def __set_name__(self, owner, name):
            if not re.match(r"[a-z][a-z_]*[a-z]$", name):
                raise AttributeError(
                    "Internal error in RuntimeOptions: invalid option name %s."
                    % name
                )
            scripting_name = name.replace("_", "-")
            owner._validators[scripting_name] = \
                lambda x: x.isdigit() and int(x) >= 0
            owner._scripting_setters[scripting_name] = self._scripting_setter
            setattr(owner, name, staticmethod(self._public_accessor))

        # class _IntervalOption
        def _public_accessor(self, value=None, say_it=False):
            if value is None:
                return self._value
            self._value = value
            if say_it:
                msg = self._msg(value)
                Output.say(msg, type_of_msg=Output.INFO)

        # class _IntervalOption
        def _scripting_setter(self, value=None, say_it=False):
            if value is None:
                value = self._get_pause_value()
                if value is None:
                    return False
            old_value = self._value
            value = int(value)
            self._public_accessor(value, say_it=True)
            return old_value != value

        @staticmethod  # class _IntervalOption
        def _get_pause_value():
            with Output.get_lock():
                Output.say(
                    _("Enter the length of the pause in seconds:"),
                    type_of_msg=Output.INTERACTION,
                )
                return UserInput.get_int()

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def valid_name(cls, name):
        return name in cls._validators

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def valid_option(cls, name, value):
        return cls._validators[name](value)

    # Boolean options currently being managed at the class level, i.e., not by
    # an instance of an option class.

    _internal_setter_getters = {
        "apply-subst": lambda *x, **y: RuntimeOptions.apply_subst(*x, **y),
        "show-subst": lambda *x, **y: RuntimeOptions.show_subst(*x, **y),
        "no-info": lambda *x, **y: RuntimeOptions.no_info(*x, **y),
    }

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def modify(cls, name, value=None):
        if name not in cls._validators:
            # It will be caught by Commands.process
            raise AttributeError()  # TODO agregar texto a la excepción
        if value is not None and not cls._validators[name](value):
            # It will be caught by Commands.process
            raise AttributeError()  # TODO agregar texto a la excepción

        if name in cls._scripting_setters:
            cls._scripting_setters[name](value, say_it=True)
        elif name in cls._internal_setter_getters:
            setter_getter = cls._internal_setter_getters[name]
            old_value = setter_getter()
            value = (
                (not old_value)
                if value is None
                else (value in cls._BooleanOption._true_values)
            )
            setter_getter(value, say_it=True)
            return old_value != setter_getter()
        elif name == "monitoring-interval":
            if value is None:
                value = cls._IntervalOption._get_pause_value()
                if value is None:
                    return False
            old_value = RuntimeOptions.monitoring_interval()
            value = int(value)
            RuntimeOptions.monitoring_interval(value, say_it=True)
            return old_value != value
        elif name == "tracking-mode":
            old_value = cls._tracking_mode
            cls._set_tracking_mode(value, say_it=True)
            return old_value != cls._tracking_mode
        elif name == "sequence-mode":
            old_value = cls._sequence_mode
            cls._set_sequence_mode(value, say_it=True)
            return old_value != cls._sequence_mode
        elif name == "feedback-mode":
            old_value = cls._feedback_mode
            cls._set_feedback_mode(value, say_it=True)
            return old_value != cls._feedback_mode
        else:
            # It will be caught by Commands.process
            raise AttributeError()

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def get(cls, name):
        if name not in cls._validators:
            # It will be caught by Commands.process
            raise AttributeError()  # TODO agregar texto a la excepción
        accessor = getattr(cls, name.replace("-", "_"))
        return accessor()

    no_showline = _BooleanOption(
        False,
        _("The current line will not be printed even if requested by the "
          "user."),
        _("The current line will be printed when requested by the user."),
    )

    no_echo = _BooleanOption(
        False,
        _("The current line will not be printed when the line number "
          "changes."),
        _("The current line will be printed when the line number changes."),
    )

    no_update_player = _BooleanOption(
        False,
        _("The player will not be restarted if the line number changes while "
          "reading."),
        _("The player will be restarted if the line number changes while "
          "reading."),
    )

    show_line_number = _BooleanOption(
        False,
        _("Line numbers will be printed."),
        _("Line numbers will not be printed."),
    )

    show_total_lines = _BooleanOption(
        False,
        _("Number of total lines will be printed."),
        _("Number of total lines will not be printed."),
    )

    stop_after_current_line = _BooleanOption(
        False,
        lambda: _("The player will stop after reading the current line.")
        if Player.running()
        else _("The player will stop after reading the next line."),
        lambda: _("The player will not stop after reading the current line.")
        if Player.running()
        else _("The player will not stop after reading the next line."),
    )

    reset_scheduled_stop_after_moving = _BooleanOption(
        True,
        _("A scheduled stop will not be reset after moving the line pointer."),
        _("A scheduled stop will be reset after moving the line pointer."),
    )

    stop_after_each_line = _BooleanOption(
        False,
        _("The player will stop after reading each line."),
        _("The player will not stop after reading each line."),
    )

    restart_after_change = _BooleanOption(
        True,
        _("The player will restart when changes to input files are detected."),
        _("The player will not restart when changes to input files are "
          "detected."),
    )

    restart_after_substitution_change = _BooleanOption(
        False,
        _("The player will restart when changes to the substituted line are "
          "detected."),
        _(
            "The player will not restart when changes to the substituted line "
            "are detected."
        ),
    )

    restart_on_touch = _BooleanOption(
        False,
        _(
            "Modification time updating without a content change will be "
            "enough to restart the player."
        ),
        _(
            "Modification time updating without a content change will not be "
            "enough to restart the player."
        ),
    )

    restarting_message_when_not_playing = _BooleanOption(
        True,
        _(
            "Spoken feedback will be given when the player is not playing and "
            "the reading is restarted in the same line."
        ),
        _(
            "Spoken feedback will not be given when the player is not playing "
            "and the reading is restarted in the same line."
        ),
    )

    reload_when_not_playing = _BooleanOption(
        True,
        _(
            "The text source will be reloaded when changes to monitored files "
            "are detected."
        ),
        _(
            "The text source will not be reloaded when changes to monitored "
            "files are detected."
        ),
    )

    close_at_end = _BooleanOption(
        False,
        _("The program will exit when the end of the text is reached."),
        _("The program will not exit when the end of the text is reached."),
    )

    quit_without_prompt = _BooleanOption(
        False,
        _("The program will not ask for confirmation when asked to quit."),
        _("The program will ask for confirmation when asked to quit."),
    )

    pause_before = _IntervalOption(
        0,
        lambda x: _(
            "The reader will pause %s second(s) before starting to read when "
            "stopped."
        ) % x,
    )

    pause_between = _IntervalOption(
        0, lambda x: _("The reader will pause %s second(s) between lines.") % x
    )

    left_indent = _IntervalOption(
        0, lambda x: _("A left indent of %s space(s) will be used.") % x
    )

    right_indent = _IntervalOption(
        0, lambda x: _("A right indent of %s space(s) will be used.") % x
    )

    window_width_adjustment = _IntervalOption(
        0, lambda x: _("%s space(s) will be added to the right indent.") % x
    )

    # Options that don't fit the option classes' framework well (yet).
    # TODO: perhaps we can make them to?

    # We let class Output manage no_info by itself, because it might need to
    # check it from outside the main thread. (In this version of
    # RuntimeOptions, access to options is reserved for the main thread, and
    # unlocked. We might want to change that in future versions.)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def no_info(cls, value=None, say_it=False):
        with Output.get_lock():
            if value is None:
                return Output.no_info()
            if say_it:
                Output.no_info(False)
                if value:
                    Output.say(
                        _("Informative messages will not be printed."),
                        type_of_msg=Output.INFO,
                    )
                else:
                    Output.say(
                        _("Informative messages will be printed."),
                        type_of_msg=Output.INFO,
                    )
            Output.no_info(value)

    NO_SUBST = _("The option cannot be set because no substitution rules were "
                 "given.")

    _apply_subst = False

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def apply_subst(cls, value=None, say_it=False):
        if value is None:
            return cls._apply_subst
        if not Substitutions.rule_files():
            if say_it:
                Output.say(cls.NO_SUBST, type_of_msg=Output.INFO)
            return
        cls._apply_subst = value
        if value:
            Substitutions.load()
        if say_it:
            if value:
                Output.say(
                    _("Substitution rules will be applied."),
                    type_of_msg=Output.INFO
                )
            else:
                Output.say(
                    _("Substitution rules will not be applied."),
                    type_of_msg=Output.INFO,
                )

    _show_subst = False

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def show_subst(cls, value=None, say_it=False):
        if value is None:
            return cls._show_subst
        if not cls._apply_subst:
            if say_it:
                Output.say(
                    _(
                        "The option cannot be set because substitutions are "
                        "not being applied."
                    ),
                    type_of_msg=Output.INFO,
                )
            return
        cls._show_subst = value
        if value:
            if not Substitutions.rule_files():
                Output.say(cls.NO_SUBST, type_of_msg=Output.INFO)
                return
            Substitutions.load()
        if say_it:
            if value:
                Output.say(
                    _(
                        "The effect of substitution rules will be shown "
                        "instead of the actual text."
                    ),
                    type_of_msg=Output.INFO,
                )
            else:
                Output.say(
                    _(
                        "The effect of substitution rules will not be shown "
                        "instead of the actual text."
                    ),
                    type_of_msg=Output.INFO,
                )

    # We let class FileMonitor manage monitoring_interval by itself, because it
    # needs to check it from outside the main thread. (In this version of
    # RuntimeOptions, access to options is reserved for the main thread, and
    # unlocked. We might want to change that in future versions.)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def monitoring_interval(cls, value=None, say_it=False):
        if value is None:
            return FileMonitor.monitoring_interval()
        FileMonitor.monitoring_interval(value)
        if say_it:
            Output.say(
                _("Files will be checked for changes each %s second(s).")
                % value,
                type_of_msg=Output.INFO,
            )

    FEEDBACK_OPTIONS = {
        "none": SpokenFeedback.NO_FEEDBACK,
        "minimum": SpokenFeedback.MINIMUM_FEEDBACK,
        "full": SpokenFeedback.FULL_FEEDBACK,
    }
    FEEDBACK_OPTIONS_REV = {v: k for k, v in FEEDBACK_OPTIONS.items()}

    _feedback_mode = SpokenFeedback.MINIMUM_FEEDBACK

    TRACKING_OPTIONS = {
        "none": TrackingController.NO_TRACKING,
        "backward": TrackingController.BACKWARD_TRACKING,
        "forward": TrackingController.FORWARD_TRACKING,
        "restart": TrackingController.RESTART_FROM_BEGINNING,
    }
    TRACKING_OPTIONS_REV = {v: k for k, v in TRACKING_OPTIONS.items()}

    _tracking_mode = TrackingController.BACKWARD_TRACKING

    SEQUENCE_OPTIONS = {
        "normal": SEQUENCE_NORMAL,
        "modified": SEQUENCE_MODIFIED,
        "random": SEQUENCE_RANDOM,
    }
    SEQUENCE_OPTIONS_REV = {v: k for k, v in SEQUENCE_OPTIONS.items()}

    _sequence_mode = SEQUENCE_NORMAL

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def tracking_mode(cls, value=None):
        if value is None:
            return cls._tracking_mode
        cls._set_tracking_mode(value)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_tracking_mode(
      cls, to_what=None,
      say_it=False,
      adjust_sequence_mode=True
    ):
        if to_what and to_what in cls.TRACKING_OPTIONS_REV:
            to_what = cls.TRACKING_OPTIONS_REV[to_what]
        cls._set_tracking_mode_aux(to_what, say_it, adjust_sequence_mode)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_tracking_mode_aux(cls, name, say_it, adjust_sequence_mode):
        if name is None:
            UserInput.choose_mode(
                _("Choose a tracking mode:"),
                cls.TRACKING_OPTIONS,
                cls.TRACKING_OPTIONS_REV[cls._tracking_mode],
                lambda value: cls._set_tracking_mode(value, say_it),
            )
        elif name in cls.TRACKING_OPTIONS:
            mode = cls.TRACKING_OPTIONS[name]
            cls._tracking_mode = mode
            if say_it:
                Output.say(
                    _("Tracking mode set to: %s.") % name,
                    type_of_msg=Output.INFO
                )
            if (
              adjust_sequence_mode
              and cls._sequence_mode is not SEQUENCE_NORMAL
            ):
                cls._set_sequence_mode(
                    SEQUENCE_NORMAL, say_it, adjust_tracking_mode=False
                )
        else:
            # It will be caught by process_command
            raise AttributeError()

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def sequence_mode(cls, value=None):
        if value is None:
            return cls._sequence_mode
        cls._set_sequence_mode(value)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_sequence_mode(
      cls,
      to_what=None,
      say_it=False,
      adjust_tracking_mode=True
    ):
        if to_what and to_what in cls.SEQUENCE_OPTIONS_REV:
            to_what = cls.SEQUENCE_OPTIONS_REV[to_what]
        cls._set_sequence_mode_aux(to_what, say_it, adjust_tracking_mode)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_sequence_mode_aux(cls, name, say_it, adjust_tracking_mode):
        if name is None:
            UserInput.choose_mode(
                _("Choose a sequence mode:"),
                cls.SEQUENCE_OPTIONS,
                cls.SEQUENCE_OPTIONS_REV[cls._sequence_mode],
                lambda value: cls._set_sequence_mode(value, say_it),
            )
        elif name in cls.SEQUENCE_OPTIONS:
            mode = cls.SEQUENCE_OPTIONS[name]
            cls._sequence_mode = mode
            if say_it:
                Output.say(
                    _("Sequence mode set to: %s.") % name,
                    type_of_msg=Output.INFO
                )
            if (
                adjust_tracking_mode
                and mode in [SEQUENCE_MODIFIED, SEQUENCE_RANDOM]
                and cls._tracking_mode != TrackingController.FORWARD_TRACKING
            ):
                cls._set_tracking_mode(
                    TrackingController.FORWARD_TRACKING,
                    say_it,
                    adjust_sequence_mode=False,
                )
        else:
            # It will be caught by process_command
            raise AttributeError()

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def feedback_mode(cls, value=None):
        if value is None:
            return cls._feedback_mode
        cls._set_feedback_mode(value)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_feedback_mode(cls, to_what=None, say_it=False):
        if to_what and to_what in cls.FEEDBACK_OPTIONS_REV:
            to_what = cls.FEEDBACK_OPTIONS_REV[to_what]
        cls._set_feedback_mode_aux(to_what, say_it)

    @classmethod  # class RuntimeOptions
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_feedback_mode_aux(cls, name, say_it):
        if name is None:
            UserInput.choose_mode(
                _("Choose a feedback mode:"),
                cls.FEEDBACK_OPTIONS,
                cls.FEEDBACK_OPTIONS_REV[cls._feedback_mode],
                lambda value: cls._set_feedback_mode(value, say_it),
            )
        elif name in cls.FEEDBACK_OPTIONS:
            cls._feedback_mode = cls.FEEDBACK_OPTIONS[name]
            if say_it:
                Output.say(
                    _("Feedback mode set to: %s.") % name,
                    type_of_msg=Output.INFO
                )
        else:
            # It will be caught by process_command
            raise AttributeError()


@staticclass
class CmdLineArgs:

    # This class does not need a lock, because all of its methods are only
    #  called from the main thread.

    # If you change these constants, all corresponding occurrences of args.*
    # need to be changed too
    SCRIPTED_MODE_SWITCH = "--scripted"
    KEY_BINDINGS_SWITCH = "--key-bindings"
    ADD_KEY_BINDINGS_SWITCH = "--add-key-bindings"
    SAVE_KEY_BINDINGS_SWITCH = "--save-default-key-bindings"
    EDIT_KEY_BINDINGS_SWITCH = "--edit-key-bindings"
    PAUSE_BEFORE_SWITCH = "--pause-before"
    PAUSE_BETWEEN_SWITCH = "--pause-between"
    LEFT_INDENT_SWITCH = "--left-indent"
    RIGHT_INDENT_SWITCH = "--right-indent"

    WRONG_OPTION_COMBINATION_MSG = _("%s and %s cannot be used at the same "
                                     "time.")

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def process(cls):
        args = cls._get_args()

        cls._check_running_instance(args)

        cls._set_encoding(args)

        if args.save_default_key_bindings:
            cls._save_default_key_bindings(args)

        if args.edit_key_bindings:
            cls._edit_key_bindings(args)

        if args.monitoring_interval <= 0:
            Main.terminate(
                _("The monitoring interval must be an integer greater than "
                  "zero.")
            )
        RuntimeOptions.monitoring_interval(args.monitoring_interval)

        WRONG_INT = _("The %s option must be an integer greater than or equal "
                      "to zero.")

        if args.pause_before < 0:
            Main.terminate(WRONG_INT % cls.PAUSE_BEFORE_SWITCH)
        RuntimeOptions.pause_before(args.pause_before)

        if args.pause_between < 0:
            Main.terminate(WRONG_INT % cls.PAUSE_BETWEEN_SWITCH)
        RuntimeOptions.pause_between(args.pause_between)

        if args.left_indent < 0:
            Main.terminate(WRONG_INT % cls.LEFT_INDENT_SWITCH)
        RuntimeOptions.left_indent(args.left_indent)

        if args.right_indent < 0:
            Main.terminate(WRONG_INT % cls.RIGHT_INDENT_SWITCH)
        RuntimeOptions.right_indent(args.right_indent)

        RuntimeOptions.window_width_adjustment(args.window_width_adjustment)

        # Default regex flags must be set before calling other code which might
        # depend on them.
        flags = args.regex_flags.strip().replace(" ", "")
        if flags:
            try:
                efabregex.set_default_flags(flags)
            except efabregex.error:
                Main.terminate(
                    _("Invalid flags for regular expressions: %s.") % flags
                )

        cls._set_language(args)

        cls._load_language_config(args)
        cls._set_voice(args)
        cls._set_espeak_options(args)
        cls._set_key_bindings(args)

        cls._get_input_source(args)
        cls._set_segmenting_mode(args)
        cls._get_transformation_rules(args, flags)
        InputTextLoader.input_command(cls._input_command)
        InputTextLoader.input_file(cls._input_file)
        InputTextLoader.transformation_rule_files(
            cls._transformation_rule_files
        )
        InputTextLoader.transformation_log_command(
            cls._transformation_log_command
        )
        cls._get_command_line_monitored_files(args)

        FileMonitor.register_group(
            cls._monitored_files, lambda: Main.event(Main.INPUT_FILE_CHANGED)
        )

        cls._set_substitution_rules(args)
        cls._set_runtime_options(args)

        Output.say(
            _("Encoding used for input: %s") % INPUT_ENCODING,
            type_of_msg=Output.INFO
        )

        FileMonitor.initialize()
        InputTextLoader.start()

    _SECURITY_WARNING = _("SECURITY WARNING: read the manual before using "
                          "this option!")
    _OPTIONS_WARNING = _("NOTE: read the manual and use with caution")

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_args(cls):
        parser = argparse.ArgumentParser(prog=PROGNAME)
        parser.add_argument(
            "--version", action="version", version="%(prog)s " + __version__
        )
        parser.add_argument("--lang")
        parser.add_argument("--encoding")
        parser.add_argument("--config-encoding")
        parser.add_argument(
            "-c",
            "--config-file",
            metavar=_("<configuration file for voice and feedback messages>"),
        )
        parser.add_argument(
            "-C",
            "--text-conversion-config",
            metavar=_("<configuration file for text conversion> %s")
            % cls._SECURITY_WARNING,
        )
        parser.add_argument(
            "-v", "--voice", metavar=_("<name of the voice to be used>")
        )
        parser.add_argument(
            "-p",
            cls.PAUSE_BEFORE_SWITCH,
            nargs="?",
            const=3,
            default=0,
            type=int,
            metavar=_("<pause length in seconds>"),
        )
        parser.add_argument(
            "-P",
            cls.PAUSE_BETWEEN_SWITCH,
            nargs="?",
            const=3,
            default=0,
            type=int,
            metavar=_("<pause length in seconds>"),
        )
        parser.add_argument(
            "-m",
            "--monitoring-interval",
            default=2,
            type=int,
            metavar=_(
                "<time to wait before checking files for modifications, in "
                "seconds>"
            ),
        )
        parser.add_argument(
            "-M",
            "--monitored-file",
            action="append",
            default=[],
            metavar=_("<name of a file that will be checked for "
                      "modifications>"),
            help=_("This option can appear multiple times."),
        )
        parser.add_argument(
            "--no-reload-when-stopped", action="store_true", default=False
        )
        parser.add_argument(
            "--no-restart-after-change", action="store_true", default=False
        )
        parser.add_argument(
            "--restart-after-substitution-change", action="store_true",
            default=False
        )
        parser.add_argument(
            "--restart-on-touch", action="store_true",
            default=False
        )
        parser.add_argument(
            "--no-restarting-message-when-not-playing",
            action="store_true",
            default=False,
        )

        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument(
            "-t", "--tracking-mode", choices=RuntimeOptions.TRACKING_OPTIONS
        )
        group.add_argument(
            "--sequence-mode",
            choices=RuntimeOptions.SEQUENCE_OPTIONS
        )

        parser.add_argument(
            "-F", "--feedback-mode", choices=RuntimeOptions.FEEDBACK_OPTIONS
        )
        parser.add_argument(
            "-u",
            "--show-subst",
            action="store_true",
            default=False
        )
        parser.add_argument(
            "-l", "--show-line-number", action="store_true", default=False
        )
        parser.add_argument(
            "-L", "--show-total-lines", action="store_true", default=False
        )
        parser.add_argument(
            "-E",
            "--close-at-end",
            action="store_true",
            default=False
        )
        parser.add_argument(
            "-f", "--force-execution", action="store_true", default=False
        )
        parser.add_argument(
            "-s",
            "--speed",
            default=DEFAULT_SPEED,
            type=int,
            metavar=_("<speed for reading, in words/minute>"),
        )
        parser.add_argument(
            "-,", "--stop-after-each-line", action="store_true", default=False
        )
        parser.add_argument(
            "-Q", "--quit-without-prompt", action="store_true", default=False
        )
        parser.add_argument(
            "-S",
            "--substitution-rules",
            "--subst",
            action="append",
            metavar=_("<file with substitution rules>"),
            default=[],
            help=_(
                "This option can appear multiple times. The files will be "
                "processed in the given order."
            ),
        )
        parser.add_argument(
            "-r",
            "--raw",
            "--do-not-apply-substitutions",
            action="store_true",
            default=False,
            help=_("Apply substitutions only when asked by the user."),
        )
        parser.add_argument(
            "--transformation-rules",
            "--transform",
            action="append",
            metavar=_("<file with transformation rules>"),
            default=[],
            help=_(
                "This option can appear multiple times. The files will be "
                "processed in the given order."
            ),
        )
        parser.add_argument(
            "--preprocess",
            action="append",
            metavar=_(
                "<a filtering command to preprocess the input> %s"
                % cls._SECURITY_WARNING
            ),
            default=[],
            help=_(
                "This option can appear multiple times. The filters will be "
                "applied in the given order."
            ),
        )
        segmenting_options = parser.add_mutually_exclusive_group()
        segmenting_options.add_argument(
            "--separator",
            default="",
            metavar=_(
                "<string or regular expression to be used as a separator>"
            ),
        )
        segmenting_options.add_argument(
            "--segment",
            default="",
            metavar=_("<regular expression for segmenting>")
        )
        parser.add_argument(
            "--regex-flags",
            default="",
            metavar=_("<global flags for regular expressions>"),
        )
        parser.add_argument("--no-echo", action="store_true", default=False)
        parser.add_argument(
            "--no-showline",
            action="store_true",
            default=False
        )
        parser.add_argument("--no-info", action="store_true", default=False)
        parser.add_argument(
            "--no-update-player",
            action="store_true",
            default=False
        )
        parser.add_argument(
            "--no-reset-scheduled-stop-after-moving",
            action="store_true",
            default=False
        )
        parser.add_argument(
            cls.LEFT_INDENT_SWITCH,
            nargs="?",
            default=0,
            type=int,
            metavar=_("<how many spaces>"),
        )
        parser.add_argument(
            cls.RIGHT_INDENT_SWITCH,
            nargs="?",
            default=0,
            type=int,
            metavar=_("<how many spaces>"),
        )
        parser.add_argument(
            "--window-width-adjustment",
            nargs="?",
            default=1 if WINDOWS else 0,
            type=int,
            choices=[0, 1],
            help=_("Default is 1 in Windows, 0 in Linux."),
        )
        group1 = parser.add_mutually_exclusive_group(required=False)
        group1.add_argument(
            "-k",
            cls.KEY_BINDINGS_SWITCH,
            default=None,
            metavar=_("<configuration file for converting keystrokes to "
                      "commands>"),
        )
        group1.add_argument(
            cls.ADD_KEY_BINDINGS_SWITCH,
            default=None,
            metavar=_(
                "<additive configuration file for converting keystrokes to "
                "commands>"
            ),
        )
        group1.add_argument(
            cls.SCRIPTED_MODE_SWITCH, action="store_true", default=False
        )
        parser.add_argument(
            "--opt",
            default="",
            metavar=_("<options that will be passed to espeak> %s")
            % cls._OPTIONS_WARNING,
            help=_("This option must use the following syntax: %s")
            % "--opt='-opt1 -opt2 ...'",
        )
        group2 = parser.add_mutually_exclusive_group(required=True)
        group2.add_argument(
            "-K",
            cls.SAVE_KEY_BINDINGS_SWITCH,
            nargs="?",
            const="-",
            default=None,
            metavar=_(
                "<file where the default configuration for keystrokes will be "
                "saved>"
            ),
        )
        group2.add_argument(
            cls.EDIT_KEY_BINDINGS_SWITCH,
            nargs="?",
            const="-",
            default=None,
            metavar=_(
                "<file where the default configuration for keystrokes will be "
                "saved/appended>"
            ),
        )
        group2.add_argument(
            "--do",
            metavar=_(
                "<command to create text to be read> %s"
            ) % cls._SECURITY_WARNING,
        )
        group2.add_argument("file", nargs="?", metavar=_("<file to be read>"))
        return parser.parse_args()

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _check_running_instance(args):
        if args.force_execution:
            return
        this_instance = os.path.basename(__file__)
        procs = None
        if PSUTIL_INSTALLED:
            procs = psutil.process_iter(["pid", "name", "cmdline"])
            procs = [x for x in procs if x.info["cmdline"]]
            procs = [x for x in procs if x.info["name"].startswith("python")]
            procs = [x for x in procs if len(x.info["cmdline"]) > 1]
            procs = [x for x in procs if x.info["cmdline"][1] == this_instance]
            procs = [x for x in procs if x.pid != os.getpid()]
        elif not LINUX:
            return
        else:
            try:
                procs = subprocess.run(
                    ["pgrep", "-a", "python"],
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.split("\n")
                procs = [x for x in procs if x]
                procs = [x for x in procs if len(x.split()) > 2]
                procs = [x for x in procs if x.split()[2] == this_instance]
                procs = [x for x in procs if x.split()[0] != str(os.getpid())]
            except Exception as e:
                Output.report_error(e)
                Output.say(
                    _("The program could not check for a running instance."),
                    type_of_msg=Output.ERROR,
                )
                Output.say(
                    _("The program will assume no instance is running."),
                    type_of_msg=Output.INFO,
                )
                return
        if procs:
            Output.say(
                _("An instance seems to be running as one of the following "
                  "processes:"),
                type_of_msg=Output.ERROR,
            )
            Output.say("\n".join(pids), type_of_msg=Output.ERROR_EXTENDED)
            Output.say(
                _("Use the %s option to force program execution.") % "-f",
                type_of_msg=Output.INFO,
            )
            Main.terminate(DEFAULT_ERROR_RETURNCODE)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_encoding(cls, args):
        global INPUT_ENCODING
        global INPUT_ENCODING_SIG
        global CONFIG_ENCODING

        INPUT_ENCODING = cls._set_encoding_aux(args.encoding)
        INPUT_ENCODING_SIG = (
            "utf-8-sig"
            if INPUT_ENCODING.lower() in ["utf-8", "utf8"]
            else INPUT_ENCODING
        )
        CONFIG_ENCODING = cls._set_encoding_aux(args.config_encoding)

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_encoding_aux(encoding):
        if encoding:
            try:
                codecs.encode("", encoding)
                return encoding
            except Exception as e:
                Main.terminate(str(e))
        else:
            return SYSTEM_ENCODING

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _save_default_key_bindings(cls, args):
        if args.scripted:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.SCRIPTED_MODE_SWITCH, cls.SAVE_KEY_BINDINGS_SWITCH)
            )
        if args.key_bindings:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.KEY_BINDINGS_SWITCH, cls.SAVE_KEY_BINDINGS_SWITCH)
            )
        if args.add_key_bindings:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.ADD_KEY_BINDINGS_SWITCH, cls.SAVE_KEY_BINDINGS_SWITCH)
            )
        output = None
        filename = args.save_default_key_bindings
        if filename == "-":
            output = sys.stdout
        elif os.path.exists(filename):
            if os.path.isfile(filename):
                if not UserInput.confirm_action(
                    _("File %s already exists. Overwrite it?") % filename
                ):
                    Main.terminate(DEFAULT_ERROR_RETURNCODE)
            else:
                Main.terminate(_("%s is not a valid file name.") % filename)
        try:
            if not output:
                output = open(filename, "w", encoding=CONFIG_ENCODING)
            for key, value in KeyBindings.DEFAULT_BINDINGS.items():
                key = repr(key).strip("'")
                key = key.replace(" ", r"\x20")
                output.write("%s\t%s\n" % (key, value))
            if output is not sys.stdout:
                Output.say(
                    _(
                        "Default keystroke configuration was saved to file: "
                        "%s\n"
                    ) % filename,
                    type_of_msg=Output.INFO,
                )
                output.close()
            Main.terminate()
        except IOError as e:
            Output.say(
                _(
                    "An error has occurred while trying to save keystroke "
                    "configuration to file: %s"
                ) % filename,
                type_of_msg=Output.ERROR,
            )
            Main.terminate(Main.REPORTED_ERROR_MSG % e)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _edit_key_bindings(cls, args):

        if args.scripted:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.SCRIPTED_MODE_SWITCH, cls.EDIT_KEY_BINDINGS_SWITCH)
            )
        if args.key_bindings:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.KEY_BINDINGS_SWITCH, cls.EDIT_KEY_BINDINGS_SWITCH)
            )
        if args.add_key_bindings:
            Main.terminate(
                cls.WRONG_OPTION_COMBINATION_MSG
                % (cls.ADD_KEY_BINDINGS_SWITCH, cls.EDIT_KEY_BINDINGS_SWITCH)
            )

        filename = args.edit_key_bindings
        do_append = False
        if filename != "-" and os.path.exists(filename):
            if os.path.isfile(filename):
                msg = _("File %s already exists. Choose an option:") % filename
                append = _("Append the key bindings at the end")
                overwrite = _("Overwrite the current file.")
                options = [append, overwrite]
                action = UserInput.choose_mode(msg, options, None)
                if action is None:
                    Main.terminate(DEFAULT_ERROR_RETURNCODE)
                elif action == overwrite:
                    if not UserInput.confirm_action(_("Are you sure?")):
                        Main.terminate(_("The action was cancelled."))
                do_append = action == append
            else:
                Main.terminate(_("%s is not a file.") % filename)

        bindings = {}

        while True:
            Output.say(
                _("Enter an action, or press <Enter> to end."),
                type_of_msg=Output.INTERACTION,
            )
            cmd = UserInput.readline().strip()
            Output.separate(Output.INTERACTION)

            if not cmd:
                break

            if not Commands.is_macro(cmd):
                Output.say(MSG_INVALID_MACRO % cmd, type_of_msg=Output.ERROR)
                continue

            parsed_command = Commands.parse(cmd)
            if not parsed_command:
                Output.say(
                    _("The action is wrong. Check the manual for proper "
                      "syntax."),
                    type_of_msg=Output.ERROR,
                )
                time.sleep(1)
                continue

            Output.say(
                _("Press the key you want to associate with the action."),
                type_of_msg=Output.INTERACTION,
            )

            key = UserInput.getch()
            key = repr(key).strip("'")
            key = key.replace(" ", r"\x20")
            Output.say(
                _("Keystroke %s will be associated with action: %s")
                % (key, cmd),
                type_of_msg=Output.INTERACTION,
            )
            bindings[key] = cmd

        if bindings:
            if filename == "-":
                output = sys.stdout
            elif not UserInput.confirm_action(
                _("Please confirm that you want to save the key bindings to "
                  "file %s.")
                % filename
            ):
                Main.terminate(DEFAULT_ERROR_RETURNCODE)
            else:
                try:
                    current_content = ""
                    if do_append:
                        with open(filename) as f:
                            current_content = f.read().strip() + "\n\n"
                    output = open(filename, "w", encoding=CONFIG_ENCODING)
                    output.write(current_content)
                except Exception as e:
                    Output.report_error(e)
                    Main.terminate(DEFAULT_ERROR_RETURNCODE)

            for key, value in bindings.items():
                output.write("%s\t%s\n" % (key, value))

            if filename != "-":
                output.close()

        Main.terminate()

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_language(args):
        global LANG

        if args.lang:
            lang = args.lang
            try:
                cp = subprocess.run(
                    ["espeak", "--voices"],
                    text=True,
                    capture_output=True,
                    check=True
                )
                # espeak doesn't necessarily end with returncode != 0 in
                # certain cases
                if cp.stderr:
                    raise Exception(cp.stderr.strip())
                tmp = cp.stdout.strip().split("\n")[1:]
                valid_languages = [x.split()[1] for x in tmp]
                if lang not in valid_languages:
                    valid_languages = " ".join(valid_languages)
                    valid_languages = textwrap.fill(
                        valid_languages,
                        Output.window_width(sys.stderr),
                        break_on_hyphens=False,
                    )
                    Main.terminate(
                        _(
                            "The language given (%s) is not valid. Valid "
                            "languages are:\n\n%s."
                        )
                        % (lang, valid_languages)
                    )
            except Exception as e:
                Output.report_error(e)
                Output.say(
                    _(
                        "An error has occurred while trying to query espeak’s "
                        "available languages."
                    ),
                    type_of_msg=Output.ERROR,
                )
                Output.say(
                    _("The program cannot determine if the given language is "
                      "valid."),
                    type_of_msg=Output.ERROR,
                )
                Output.say(
                    _("The program will try to use the given language (%s) "
                      "anyway.")
                    % lang,
                    type_of_msg=Output.INFO,
                )
        else:
            lang = locale.getdefaultlocale()[0].split("_")[0]
        Output.say(
            _("Language used for reading: %s") % lang,
            type_of_msg=Output.INFO
        )
        LANG = lang

    LOCALE_CONFIG_ELEMENT = r"^([a-z-]+):\s*(.+)$"

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _load_language_config(cls, args):
        if args.config_file:
            cls._check_file_validity(args.config_file)
            fns = [args.config_file]
        else:
            fns = [
                sys.path[0] + "/%s.%s.cfg" % (PROGNAME, LANG),
                sys.path[0] + "/%s.cfg" % PROGNAME,
            ]
        for fn in fns:
            if os.path.isfile(fn):
                Output.say(
                    _("Language configuration file: %s") % fn,
                    type_of_msg=Output.INFO
                )
                cls._load_language_config_aux(fn)
                return
        Output.say(
            _("No language configuration file was provided."),
            type_of_msg=Output.INFO
        )

    _voice = None

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _load_language_config_aux(cls, fn):
        conf = cls._read_config_file(fn).strip()
        conf = conf.split("\n")
        conf = list(map(str.strip, conf))
        conf = [x for x in conf if not x or x[0] != "#"]
        loc_tmp = {}
        valid_keys = ["voice"] + list(SpokenFeedback.keys())
        for line in conf:
            line = line.strip()
            m = re.match(cls.LOCALE_CONFIG_ELEMENT, line)
            if not m:
                Output.say(
                    _("Wrong syntax in file: %s.") % fn,
                    type_of_msg=Output.ERROR
                )
                Main.terminate(_("The wrong line is: %s") % line)
                return
            key = m.group(1)
            value = m.group(2)
            if key not in valid_keys:
                Output.say(
                    _("Wrong option name in file: %s.") % fn,
                    type_of_msg=Output.ERROR
                )
                Main.terminate(_("The wrong option name is: %s") % key)
                return
            elif key == "voice":
                cls._voice = value
            else:
                SpokenFeedback.set_message(key, value)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _read_config_file(cls, fn):
        cls._check_file_validity(fn)
        try:
            with open(fn, "r", encoding=CONFIG_ENCODING) as f:
                return f.read()
        except IOError as e:
            Output.say(
                _("There was an error trying to read from file: %s") % fn,
                type_of_msg=Output.ERROR,
            )
            Main.terminate(Main.REPORTED_ERROR_MSG % e)

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _check_file_validity(fn, allow_dir=False):
        if not os.path.exists(fn):
            Main.terminate(_("The file %s does not exist.") % fn)
        elif not allow_dir and not os.path.isfile(fn):
            Main.terminate(_("%s is not a file.") % fn)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_voice(cls, args):
        voice = None
        voices = []
        if args.voice:
            voices = [args.voice]
        elif cls._voice is not None:
            voices = [cls._voice]
        else:
            try:
                # Be VERY careful to ensure LANG is sanitized (shlex.quote).
                cp = subprocess.run(
                    ["espeak", "--voices=%s" % shlex.quote(LANG)],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                if cp.stderr:
                    # espeak doesn't necessarily end with returncode != 0 in
                    # certain cases
                    raise Exception(cp.stderr.strip())
                tmp = cp.stdout.strip().split("\n")[1:]
                if tmp:
                    tmp2 = [x for x in tmp if "mbrola" in x or "-mb-" in x]
                    if tmp2:
                        voices.append(tmp2[0].split()[3])
                    tmp2 = [
                      x for x in tmp if "mbrola" not in x and "-mb-" not in x
                    ]
                    if tmp2:
                        voices.append(tmp2[0].split()[3])
                else:
                    Output.say(
                        _("No voices for language %s were found.") % LANG,
                        type_of_msg=Output.ERROR,
                    )
            except Exception as e:
                Output.report_error(e)
                Output.say(
                    _(
                        "An error has occurred while trying to query espeak’s "
                        "available voices."
                    ),
                    type_of_msg=Output.ERROR,
                )
        if voices:
            for v in voices:
                try:
                    # Sanitizing 'v' is not necessary, provided the following
                    # command is given as an array. Be VERY careful to provide
                    # sanitization if you were to make the following call
                    # through a shell.
                    cp = subprocess.run(
                        ["espeak", "-v", v, " "],
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    if cp.stderr:
                        # espeak doesn't necessarily end with returncode != 0
                        # in certain cases
                        raise Exception(cp.stderr.strip())
                    else:
                        voice = v
                        break
                except Exception as e:
                    Output.report_error(e)
                    Output.say(
                        _("An error has occurred while testing espeak with "
                          "voice %s.") % v,
                        type_of_msg=Output.ERROR,
                    )
        if voice:
            EspeakController.voice(voice)
            Output.say(
                _("Voice used for reading: %s") % voice,
                type_of_msg=Output.INFO
            )
        else:
            Output.say(
                _(
                    "The voice for reading could not be determined, the "
                    "program will try to use espeak’s default voice."
                ),
                type_of_msg=Output.INFO,
            )

    # If you modify this method, be VERY careful to sanitize args.opt
    # (shlex.split or shlex.quote where appropriate), in case the call were
    # ever to be made through a shell.
    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_espeak_options(args):
        if args.opt:
            try:
                espeak_options = shlex.split(args.opt)
                cmd = ["espeak"] + espeak_options + [" "]
                cp = subprocess.run(
                    cmd,
                    text=True,
                    capture_output=True,
                    check=True
                )
                if cp.stderr:
                    # espeak doesn't necessarily end with returncode != 0 in
                    # certain cases
                    raise Exception(cp.stderr.strip())
                EspeakController.options(espeak_options)
            except Exception as e:
                Output.say(
                    _("Wrong options for espeak were given: %s.") % args.opt,
                    type_of_msg=Output.ERROR,
                )
                Main.terminate(Main.REPORTED_ERROR_MSG % e)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_key_bindings(cls, args):
        filename = (
            args.key_bindings
            or args.add_key_bindings
            or cls._get_default_key_bindings_file()
        )
        if not filename:
            key_bindings = KeyBindings.DEFAULT_BINDINGS
        else:
            cls._check_file_validity(filename)
            _bindings = cls._read_config_file(filename)
            _bindings = _bindings.split("\n")
            # Be careful not to delete next line
            _bindings = list(map(str.strip, _bindings))
            _bindings = [x for x in _bindings if x]
            _bindings = [x for x in _bindings if not x.startswith("#")]
            _processed_bindings = []
            if args.add_key_bindings is not None:
                key_bindings = KeyBindings.DEFAULT_BINDINGS
            else:
                key_bindings = {}
            for binding in _bindings:
                # binding was already stripped of spaces above
                m = re.match(r"^(\S+)\s+(.+)$", binding)
                if not m:
                    cls._report_key_binding_error(
                        _(
                            "The following line is wrong: '%s'. Key bindings "
                            "must consist of a key specification, followed by "
                            "one or more spaces, followed by the desired "
                            "action."
                          ) % binding,
                        filename,
                    )
                key = translate_control_chars(m.group(1))
                value = m.group(2)
                if not Commands.is_macro(value):
                    # In this version, we only allow macros in key conf. files
                    cls._report_key_binding_error(
                        MSG_INVALID_MACRO % value,
                        filename,
                    )
                if key in _processed_bindings:
                    cls._report_key_binding_error(
                        _(
                            "The following keystroke appears more than once "
                            "in the configuration file: %s"
                        ) % key,
                        filename,
                    )
                else:
                    _processed_bindings.append(key)
                if key in key_bindings:
                    Output.say(
                        _("The binding for key %s has been redefined to be "
                          "'%s'.") % (repr(key), value),
                        type_of_msg=Output.INFO,
                    )
                key_bindings[key] = value
        binding_for_quit = False
        for key, binding in key_bindings.items():
            parsed_command = Commands.parse(binding)
            if not parsed_command:
                cls._report_key_binding_error(
                    _("The following action is wrong: %s") % binding, filename
                )
            elif Commands.contains_quit(parsed_command):
                binding_for_quit = True
        if not binding_for_quit:
            cls._report_key_binding_error(
                _("A keystroke must be configured for the '%s' or '%s' "
                  "action.") % (MACRO_QUIT_ASK, MACRO_QUIT_NOW),
                filename,
            )
        KeyBindings.set(key_bindings)

    DEFAULT_KEY_BINDINGS_FILE = sys.path[0] + "/%s.key" % PROGNAME

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_default_key_bindings_file(cls):
        if os.path.isfile(cls.DEFAULT_KEY_BINDINGS_FILE):
            return cls.DEFAULT_KEY_BINDINGS_FILE
        return None

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _report_key_binding_error(e, filename=None):
        if filename:
            Output.say(
                _("Error in keystroke configuration file: %s.")
                % filename,
                type_of_msg=Output.ERROR,
            )
        else:
            Output.say("Internal error.", type_of_msg=Output.ERROR)
        Main.terminate(Main.REPORTED_ERROR_MSG % e)

    _input_command = None
    _input_file = None
    _monitored_files = []
    _command_line_monitored_files = []
    _transformation_log_command = None

    # If you modify this method, be VERY careful to ensure input_command is
    # sanitized (shlex.quote where appropriate), to avoid a 'command
    # injection'. InputTextLoader depends on receiving a sanitized input
    # command.
    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_input_source(cls, args):
        if args.do is not None:
            # No sanitizing is possible here, it is up to the user
            if LINUX:
                cls._input_command = "%s -c %s" % (
                    os.environ["SHELL"],
                    shlex.quote(args.do),
                )
            elif WINDOWS:
                cls._input_command = "cmd /C %s" % shlex.quote(args.do)
            else:
                traceback.print_stack()
                Main.terminate(UNSUPPORTED_PLATFORM)
        elif args.file is not None:
            cls._check_file_validity(args.file)
            cls._input_file = args.file
            cls._monitored_files = [args.file]
            if not (LINUX or WINDOWS):
                traceback.print_stack()
                Main.terminate(UNSUPPORTED_PLATFORM)
            if LINUX:
                mt = "text/plain"
                try:
                    # Sanitizing args.file is not necessary, provided the
                    # command is given as an array. Be VERY careful to provide
                    # sanitization in case you make the following call through
                    # a shell.
                    mt = subprocess.run(
                        ["mimetype", "-b", "-L", args.file],
                        text=True,
                        capture_output=True,
                        check=True,
                    ).stdout.strip()
                except Exception as e:
                    Output.report_error(e)
                    Output.say(
                        _(
                            "The program could not determine the mimetype of "
                            "the file: %s"
                        ) % args.file,
                        type_of_msg=Output.ERROR,
                    )
                    Output.say(
                        _("The program will assume the input file’s mimetype "
                          "is %s.") % mt,
                        type_of_msg=Output.INFO,
                    )
            else:
                mt = (
                  "text/plain"
                  if cls._input_file.lower().endswith(".txt")
                  else None
                )
            if mt == "text/plain":
                if LINUX:
                    cls._input_command = "cat " + shlex.quote(cls._input_file)
                else:
                    cls._input_command = "cmd /C type " + shlex.quote(
                        cls._input_file
                    )
            else:
                conversion_option = (
                    "--config-file %s " % shlex.quote(
                        args.text_conversion_config
                    )
                    if args.text_conversion_config
                    else ""
                )
                cls._input_command = "%s %s --lang %s %s" % (
                    EFABCONV,
                    conversion_option,
                    shlex.quote(LANG),
                    shlex.quote(cls._input_file),
                )

        for the_filter in args.preprocess:
            # No sanitizing is possible here, it is up to the user
            cls._input_command += " | " + the_filter

    # If you modify this method, be VERY careful to ensure _input_command and
    # _transformation_log_command are sanitized (shlex.quote where appropriate)
    # to avoid a 'command injection'. InputTextLoader and depends on receiving
    # sanitized commands.
    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_transformation_rules(cls, args, flags):
        cls._transformation_rule_files = list(
            map(os.path.expanduser, args.transformation_rules)
        )
        transformation_option = ""
        for fn in cls._transformation_rule_files:
            cls._check_file_validity(fn)
            transformation_option += " -f %s " % shlex.quote(fn)
            if fn not in cls._monitored_files:
                cls._monitored_files.append(fn)
        if transformation_option:
            if flags:
                transformation_option = "--regex-flags %s %s " % (
                    shlex.quote(flags),
                    transformation_option,
                )
            transformation_option += "--encoding %s --config-encoding %s " % (
                shlex.quote(INPUT_ENCODING),
                shlex.quote(CONFIG_ENCODING),
            )
            cls._input_command += " | %s %s" % (
                EFABTRANS,
                transformation_option
            )
            cls._transformation_log_command = cls._input_command + " --log"

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _get_command_line_monitored_files(cls, args):
        if args.monitored_file:
            for fn in args.monitored_file:
                cls._check_file_validity(fn, allow_dir=True)
                if fn not in cls._monitored_files:
                    cls._command_line_monitored_files.append(fn)
                    cls._monitored_files.append(fn)
                else:
                    Main.terminate(_("The file %s does not exist.") % fn)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def monitored_files(cls):
        return cls._command_line_monitored_files

    WRONG_SEPARATOR_REGEX = _(
        "Wrong regular expression given for separator: %s"
    )
    UNTERMINATED_SEPARATOR_REGEX = _(
        "Unterminated regular expression given for separator: %s"
    )
    INVALID_SEPARATOR_FLAGS = _("Invalid flags given for separator: %s")
    SUBSTITUTION_SEPARATOR = _(
        "A substitution expression cannot be used as a separator: %s"
    )
    WRONG_SEGMENTING_REGEX = _(
        "Wrong regular expression given for segmenting: %s"
    )
    UNTERMINATED_SEGMENTING_REGEX = _(
        "Unterminated regular expression given for segmenting: %s"
    )
    INVALID_SEGMENTING_FLAGS = _("Invalid flags given for segmenting: %s")
    SUBSTITUTION_SEGMENTING = _(
        "A substitution expression cannot be used for segmenting: %s"
    )

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_segmenting_mode(cls, args):

        what = args.separator or args.segment
        if not what:
            return
        if efabregex.is_substitution(what):
            Main.terminate(
                (
                    cls.SUBSTITUTION_SEPARATOR
                    if what is args.separator
                    else cls.SUBSTITUTION_SEGMENTING
                )
                % what
            )
        elif efabregex.is_unterminated(what):
            Main.terminate(
                (
                    cls.UNTERMINATED_SEPARATOR_REGEX
                    if what is args.separator
                    else cls.UNTERMINATED_SEGMENTING_REGEX
                )
                % what
            )
        elif efabregex.contains_invalid_flags(what):
            Main.terminate(
                (
                    cls.INVALID_SEPARATOR_FLAGS
                    if what is args.separator
                    else cls.INVALID_SEGMENTING_FLAGS
                )
                % what
            )
        elif efabregex.is_pattern(what):
            regex = what
        elif what is args.separator:
            InputTextLoader.separator_string(translate_control_chars(what))
            return
        else:
            regex = efabregex.create_match(what)
        try:
            regex_object, pattern = efabregex.compile(regex)
            if what is args.separator:
                InputTextLoader.separator_regex(pattern)
            else:
                InputTextLoader.segmenting_regex(pattern)
        except efabregex.error as e:
            Output.say(
                (
                    cls.WRONG_SEPARATOR_REGEX
                    if what is args.separator
                    else cls.WRONG_SEGMENTING_REGEX
                )
                % what,
                type_of_msg=Output.ERROR,
            )
            Main.terminate(Main.REPORTED_ERROR_MSG % e)

    @classmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_substitution_rules(cls, args):
        substitution_rule_files = []
        for fn in list(map(os.path.expanduser, args.substitution_rules)):
            cls._check_file_validity(fn)
            if fn not in substitution_rule_files:
                substitution_rule_files.append(fn)
        if substitution_rule_files:
            Substitutions.rule_files(substitution_rule_files)
            Substitutions.load()
            RuntimeOptions.apply_subst(not args.raw)
            FileMonitor.register_group(
                substitution_rule_files,
                lambda: Main.event(Main.SUBST_RULES_FILE_CHANGED),
            )
        else:
            RuntimeOptions.apply_subst(False)

    @staticmethod  # class CmdLineArgs
    # Executed only in main thread. Uncomment the following decorator...
    # @mainthreadmethod
    # ... to enforce check at runtime.
    def _set_runtime_options(args):
        RuntimeOptions.restart_after_change(not args.no_restart_after_change)
        RuntimeOptions.restart_after_substitution_change(
            args.restart_after_substitution_change
        )
        RuntimeOptions.restart_on_touch(args.restart_on_touch)
        RuntimeOptions.restarting_message_when_not_playing(
            not args.no_restarting_message_when_not_playing
        )
        RuntimeOptions.reload_when_not_playing(not args.no_reload_when_stopped)
        RuntimeOptions.show_line_number(args.show_line_number)
        RuntimeOptions.no_echo(args.no_echo)
        RuntimeOptions.no_showline(args.no_showline)
        RuntimeOptions.no_info(args.no_info)
        RuntimeOptions.no_update_player(args.no_update_player)
        RuntimeOptions.reset_scheduled_stop_after_moving(
            not args.no_reset_scheduled_stop_after_moving
        )
        RuntimeOptions.show_total_lines(args.show_total_lines)
        RuntimeOptions.stop_after_each_line(args.stop_after_each_line)
        RuntimeOptions.show_subst(args.show_subst)
        RuntimeOptions.close_at_end(args.close_at_end)
        RuntimeOptions.quit_without_prompt(args.quit_without_prompt)
        if args.speed < MINSPEED or args.speed > MAXSPEED:
            Main.terminate(
                _("The speed cannot be less than %s nor greater than %s.")
                % (MINSPEED, MAXSPEED)
            )
        EspeakController.speed(args.speed)
        if args.tracking_mode is not None:
            RuntimeOptions.tracking_mode(args.tracking_mode)
        elif args.sequence_mode is not None:
            RuntimeOptions.sequence_mode(args.sequence_mode)
        if args.feedback_mode is not None:
            RuntimeOptions.feedback_mode(args.feedback_mode)
        Main.scripted_mode = args.scripted


###############################################################################
# PROGRAM ENTRY POINT

if __name__ == "__main__":
    CmdLineArgs.process()
    Main.run_safely(Main.run)
else:
    print(_("This module is not for import."), file=sys.stderr)
    sys.modules[__name__] = None
