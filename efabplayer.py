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
import efabtracking
from efabcore import start_daemon, terminate, pause
from efabseq import (
    SequenceNormal, SequenceRandom, SequenceModified, StateProtocol
)

if TYPE_CHECKING:
    _ = gettext.gettext


_ESPEAK_ERROR = _("An error has occurred while trying to run espeak.")
_ESPEAK_ERROR_STOPPED = _("The reading is stopped, you can try to restart it.")

_FOUND = _("A match was found for the search expression (%s) at line %s.")
_FOUND_SAME = _(
    "A match was found for the search expression (%s) at the current line "
    "(%s)."
)
_NOT_FOUND = _("A match was not found for the search expression (%s).")

_SUBST_APPLY = _("New substitution rules apply to this line. Restarting.")
_SUBST_ON_RESTART = _(
    "New substitutions will be applied when reading is restarted."
)
_SUBST_BUT_PAUSED = _(
    "New substitutions will not be applied to the current line, as the player "
    "is paused. Stop/restart the player to apply the new substitutions."
)
_SUBST_DONT_APPLY = _("New substitution rules do not affect this line.")

_WAIT_FOR_CHANGES = _("Waiting for changes.")
_STOP_EACH_LINE = _("The player is stopping at the end of each line.")
_PLAYER_RESET = _("The player was reset to the beginning of the current line.")
_RELOAD_ON_RESTART = _("The input file will be reloaded upon restart.")

_BACK_ONE_LINE = _("Back one line.")
_CHOOSING_RANDOM = _("Choosing a random line.")
_NO_MODIFIED_AFTER = _("There are no modified lines after this one.")
_NO_MODIFIED_BEFORE = _("There are no modified lines before this one.")
_SKIPPING_NEXT_MODIFIED = _("Skipping to the next modified line.")
_SKIPPING_PREV_MODIFIED = _("Skipping to the previous modified line.")


def _popen_espeak(
    line: str,
    speed: int = DEFAULT_SPEED,
    voice: Optional[str] = None,
    espeak_options: Optional[str] = None
) -> Tuple[Optional[subprocess.Popen], Optional[Exception]]:
    # Prevent an initial hyphen to be taken as an option:
    line = line.lstrip(" -")
    d = ["espeak", "-s", str(speed)]
    if voice:
        d += ["-v", voice]
    if espeak_options:
        # No sanitizing is possible here, it is up to the user
        d += shlex.split(espeak_options)
    d += [line]
    # In case you modify this method, be VERY careful to ensure
    # sanitization if you were to make the call through a shell.
    try:
        return subprocess.Popen(d, text=True, stderr=subprocess.PIPE), None
    except Exception as e:
        return None, e


def _run_espeak(
    line: str,
    speed: int = DEFAULT_SPEED,
    voice: Optional[str] = None,
    espeak_options: Optional[str] = None,
    on_start=Callable[[subprocess.Popen], None]
) -> bool:

    espeak, err = _popen_espeak(line, speed, voice, espeak_options)
    if espeak is not None:
        if on_start:
            on_start(espeak)
        atexit.register(espeak.terminate)
        stdout, stderr = espeak.communicate()
        atexit.unregister(espeak.terminate)
        if stderr:
            efablogger.say(stderr, type_of_msg=efablogger.ERROR_EXTENDED)
        return True
    elif err is not None:
        _report_unable_to_run_espeak(err)
        return False
    else:
        return False


def _report_unable_to_run_espeak(e: Exception) -> None:
    with efablogger.lock:
        efablogger.say(_ESPEAK_ERROR, type_of_msg=efablogger.ERROR)
        efablogger.report_error(e)


def _stop_espeak(espeak: Optional[subprocess.Popen], paused: bool) -> None:
    if _espeak_running(espeak):
        assert espeak is not None
        if LINUX and paused:
            # Otherwise, terminate() won't do.
            espeak.send_signal(signal.SIGCONT)
        espeak.terminate()


def _espeak_running(espeak: Optional[subprocess.Popen]) -> bool:
    return espeak is not None and espeak.poll() is None


def _toggle_espeak(espeak: Optional[subprocess.Popen], paused: bool) -> bool:
    if _espeak_running(espeak):
        assert espeak is not None
        paused = not paused
        if LINUX:
            espeak.send_signal(signal.SIGSTOP if paused else signal.SIGCONT)
        elif WINDOWS:
            paused = _toggle_espeak_for_windows(espeak, paused)
        else:
            traceback.print_stack()
            terminate(UNSUPPORTED_PLATFORM)
    return paused


def _toggle_espeak_for_windows(espeak: subprocess.Popen, paused: bool) -> bool:
    if PSUTIL_INSTALLED:
        if paused:
            psutil.Process(espeak.pid).suspend()
        else:
            psutil.Process(espeak.pid).resume()
        return paused
    elif PSSUSPEND:
        if paused:
            cmd = [PSSUSPEND, str(espeak.pid)]
        else:
            cmd = [PSSUSPEND, "-r", str(espeak.pid)]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return paused
        except Exception:
            return not paused
    else:
        return not paused


class _BasicPlayer:

    """The _BasicPlayer class implements the basic functionality for reading a
    list of strings thru espeak, with the ability to query and stop the reading
    from from another thread."""

    def __init__(self, *, lines, options):
        self._lines = lines
        self._voice = options.voice
        self._speed = options.speed
        self._lock = threading.RLock()
        self._espeak = None
        self._playing = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()

    def play(self):
        self._playing.set()
        self._stopped.clear()

        for line in self._lines:
            _run_espeak(
                line,
                voice=self._voice,
                speed=self._speed,
                on_start=self._register,
            )
            if not self._playing.is_set():
                break

        self._stopped.set()

    def _register(self, espeak):
        with self._lock:
            self._espeak = espeak

    def playing(self):
        return not self._stopped.is_set()

    def running(self):
        return self.playing()

    def stop(self):
        self._playing.clear()
        with self._lock:
            if _espeak_running(self._espeak):
                _stop_espeak(self._espeak, False)
        self._stopped.wait()


# A thin wrapper around queue.Queue. We will use this to keep shared state.


class _Store(queue.Queue):
    def __init__(self):
        super().__init__(maxsize=1)

    def get(self, block=True, timeout=None):
        try:
            return super().get(block=block, timeout=timeout)
        except queue.Empty:
            return None


@dataclass
class StoredSearch:
    expression: str
    pattern: re.Pattern


# Auxiliar constants representing movement actions. Must match the method names
# in the efabseq module.


_FIRST = "first"
_PREV = "previous"
_NEXT = "next"
_LAST = "last"


# Immutable objects representing the current state of the player.


@dataclass(frozen=True)
class PlayerState(StateProtocol):
    text: Optional[str] = None
    lines: List[str] = field(default_factory=list)
    modified_lines: List[int] = field(default_factory=list)
    pointer: int = 0
    jump_to: Optional[int] = None
    eol: bool = False
    do_not_pause_before: bool = False
    line_being_read: Optional[str] = None
    last_shown_line: Optional[Tuple[int, str, int]] = None
    stored_search: Optional[StoredSearch] = None
    reload_scheduled: bool = False
    loader: Optional[Callable] = None
    said_anything: bool = False
    espeak: Optional[subprocess.Popen] = None
    action: Optional[int] = None


# Values for state.action


_STOP = 0
_RESTART = 1


# A decorator to simplify the definition of player methods which operate on
# state and return an updated state and an additional value.


R_OUTER = Any
R_INNER = Tuple[PlayerState, R_OUTER]
P = ParamSpec("P")


def _state(
    f: Callable[Concatenate["Player", PlayerState, P], R_INNER]
) -> Callable[Concatenate["Player", P], R_OUTER]:
    def wrapper(self: "Player", *args: P.args, **kwargs: P.kwargs) -> R_OUTER:
        old_state = self._getstate()
        try:
            tmp = f(self, old_state, *args, **kwargs)
            self._putstate(tmp[0])
            return tmp[1]
        except Exception as e:
            self._putstate(old_state)
            raise e
    return wrapper


# Here begins the definition of the Player class, the main object implementing
# the functionality of this program.


class Player:
    def __init__(self, options, substitutions, feedback_messages):

        # Use a _Store object to keep shared state (first level of
        # synchronization, between the worker thread and a client thread).
        self._store = _Store()
        self._store.put(PlayerState())

        # Use a lock to protect access to the store itself (second level of
        # synchronization, between different client threads which might try to
        # issue commands at the same time). In this version this is used by the
        # efabcore module and the helper _Updater class below.
        self.lock = threading.RLock()

        self.options = options
        self._substitutions = substitutions
        self._feedback_messages = feedback_messages
        self._updater = _Updater(self)
        atexit.register(self._updater.stop_update)

        self._playing = threading.Event()
        self._paused = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._worker_thread = start_daemon(self._run)

    def _putstate(self, state: PlayerState) -> None:
        assert isinstance(state, PlayerState)
        self._store.put(state)

    def _getstate(self) -> PlayerState:
        if threading.current_thread() == self._worker_thread:
            return self._store.get()
        else:
            with self.lock:
                return self._store.get()

    def _run(self):
        while True:
            self._playing.wait()
            self._stopped.clear()
            self._play()
            self._playing.clear()
            self._paused.clear()
            self._stopped.set()

    def running(self) -> bool:
        return self._playing.is_set()

    def running_and_paused(self) -> bool:
        return self._playing.is_set() and self._paused.is_set()

    def running_and_not_paused(self) -> bool:
        return self._playing.is_set() and not self._paused.is_set()

    @_state
    def text_is_loaded(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return state, state.text is not None

    @_state
    def last_line_number(self, state: PlayerState) -> Tuple[PlayerState, int]:
        return state, len(state.lines)

    @_state
    def current_line_number(
        self, state: PlayerState
    ) -> Tuple[PlayerState, int]:
        return state, state.pointer + 1

    def set_text(self, text: str, lines: List[str]) -> None:
        if self._updater.running():
            # This will get called if the input file changes while feedback on
            # previous changes is still being read. In that case, the store is
            # empty and the updater has exclusive access to the player's state.
            self._updater.run(None, text, lines)
        else:
            state = self._getstate()
            state = replace(state, reload_scheduled=False)
            if state.text is None:  # First call to set_text()
                self._first_load(state, text, lines)
            else:
                self._updater.run(state, text, lines)

    def _first_load(
        self, state: PlayerState, text: str, lines: List[str]
    ) -> None:
        new_state = replace(state, text=text, lines=lines, pointer=0)
        if self.options.sequence_mode is SequenceModified:
            efablogger.say(_WAIT_FOR_CHANGES, type_of_msg=efablogger.INFO)
        else:
            first = self.options.sequence_mode.first(new_state)
            new_state = replace(new_state, jump_to=first)
            new_state = self._start(new_state)
        self._putstate(new_state)

    def _start(self, state: PlayerState) -> PlayerState:
        if state.reload_scheduled:
            start_daemon(state.loader)
            state = replace(state, reload_scheduled=False, loader=None)
        if not self._playing.is_set():
            if state.eol:
                state = replace(
                    state, jump_to=self.options.sequence_mode.next(state)
                )
            self._paused.clear()
            self._playing.set()
        return state

    def _play(self):
        state = self._getstate()
        state = self._presequencer(state)
        state = self._sequencer(state)
        state = self._postsequencer(state)
        state = replace(state, action=None)
        self._putstate(state)

    def _presequencer(self, state: PlayerState) -> PlayerState:
        if state.do_not_pause_before:
            state = replace(state, do_not_pause_before=False)
        else:
            pause(self.options.pause_before)
        return state

    def _sequencer(self, state: PlayerState) -> PlayerState:
        while self._playing.is_set() and state.pointer < len(state.lines):
            state = self._jump_to(state)
            line = self._line_to_say(state)
            state = replace(state, line_being_read=line)
            state = self._call_espeak(state, line)
            state = replace(state, said_anything=True)
            if state.action == _RESTART:
                state = replace(state, action=None)
                continue
            elif state.action == _STOP:
                break
            elif self.options.sequence_mode.eof(state):
                break
            else:
                state = self._between_lines(state)
                if state.action == _STOP:
                    break
            pause(self.options.pause_between)
            state = self._go(state, self.options.sequence_mode.next(state))
        return state

    def _jump_to(self, state: PlayerState) -> PlayerState:
        if state.jump_to is not None:
            state = self._go(state, state.jump_to)
        return state

    def _call_espeak(self, state: PlayerState, line: str) -> PlayerState:
        if _run_espeak(
            line,
            voice=self.options.voice,
            speed=self.options.speed,
            espeak_options=self.options.espeak_options,
            on_start=lambda espeak: self._espeak_started(state, espeak),
        ):
            state = self._getstate()
            return state
        else:
            self._report_error()
            return self._stop(state)

    def _espeak_started(
        self, state: PlayerState, espeak: subprocess.Popen
    ) -> None:
        state, _ = self._showline(state)
        self._paused.clear()
        self._putstate(replace(state, espeak=espeak))

    def _report_error(self) -> None:
        efablogger.say(_ESPEAK_ERROR_STOPPED, type_of_msg=efablogger.INFO)

    def _between_lines(self, state: PlayerState) -> PlayerState:
        if (
            self.options.stop_after_current_line
            or self.options.stop_after_each_line
        ):
            state = self._stop(state)
            state = replace(state, eol=True)
            if self.options.stop_after_current_line:
                self.options.stop_after_current_line = False
            if self.options.stop_after_each_line:
                efablogger.say(_STOP_EACH_LINE, type_of_msg=efablogger.INFO)
        return state

    def _postsequencer(self, state: PlayerState) -> Optional[PlayerState]:
        if state.action == _STOP:
            return state
        elif self.options.sequence_mode.eof(state):
            if (
                self.options.sequence_mode is SequenceNormal
                and self.options.close_at_end
            ):
                terminate()
        return state

    def stop(self) -> bool:
        if not self._playing.is_set():
            return False
        else:
            state = self._getstate()
            state = self._stop(state)
            self._putstate(state)
            self._stopped.wait()
            return True

    def _stop(self, state: PlayerState) -> PlayerState:
        if self._playing.is_set():
            _stop_espeak(state.espeak, self._paused.is_set())
            state = replace(state, espeak=None, action=_STOP)
        return state

    @_state
    def toggle(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        if not self._playing.is_set():
            return self._start(state), True
        elif not _espeak_running(state.espeak):
            return self._stop(state), True
        else:
            paused = self._paused.is_set()
            new_paused = _toggle_espeak(state.espeak, paused)
            (self._paused.set if new_paused else self._paused.clear)()
            return state, new_paused != paused

    @_state
    def restart(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        running_now = self._playing.is_set()
        return self._restart(state), not running_now

    def _restart(self, state: PlayerState) -> PlayerState:
        if self._playing.is_set():
            _stop_espeak(state.espeak, self._paused.is_set())
            state = replace(state, action=_RESTART)
        else:
            state = self._reset_pointer(state, say_it=False)
            state = replace(state, do_not_pause_before=True)
            state = self._start(state)
        return state

    @_state
    def reset_pointer(
        self, state: PlayerState, say_it=True
    ) -> Tuple[PlayerState, bool]:
        new_state = self._reset_pointer(state, say_it)
        return new_state, new_state.eol != state.eol

    def _reset_pointer(self, state: PlayerState, say_it=True) -> PlayerState:
        if state.eol:
            state = replace(state, eol=False)
            if say_it:
                efablogger.say(_PLAYER_RESET, type_of_msg=efablogger.INFO)
        return state

    @_state
    def go(
        self, state: PlayerState, line_number: int
    ) -> Tuple[PlayerState, bool]:
        new_state = self._go(state, line_number - 1)
        return new_state, new_state.pointer != state.pointer

    def _go(self, state: PlayerState, pointer: int) -> PlayerState:
        if pointer >= 0 and pointer < len(state.lines):
            if pointer == state.pointer:
                state = self._reset_pointer(state)
            else:
                if (
                    self.options.stop_after_current_line
                    and self.options.reset_scheduled_stop_after_moving
                ):
                    self.options.stop_after_current_line = False
                    self.options.log("stop-after-current-line")
                state = replace(state, pointer=pointer, eol=False)
                state = self._update_player(state)
            state, _ = self._showline(state)
        state = replace(state, jump_to=None)
        return state

    @_state
    def update_player(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        new_state = self._update_player(state, True)
        return new_state, new_state != state

    def _update_player(
        self, state: PlayerState, by_command=False
    ) -> PlayerState:
        if self.options.no_update_player and not by_command:
            return state
        elif _espeak_running(state.espeak):
            if self._paused.is_set():
                state = self._stop(state)
            else:
                _stop_espeak(state.espeak, False)
                state = self._restart(state)
        return state

    @_state
    def showline(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._showline(state, by_command=True)

    def _showline(
        self, state: PlayerState, by_command=False
    ) -> Tuple[PlayerState, bool]:
        if self.options.no_showline:
            return state, False
        if self.options.no_echo and not by_command:
            return state, False
        text = self._line_to_show(state)
        if self.options.show_line_number:
            lineno = str(state.pointer + 1)
            tot = (
                ("/" + str(len(state.lines)))
                if self.options.show_total_lines
                else ""
            )
            text = "<%s%s> %s" % (lineno, tot, text)
        return self._showline_without_repetition(state, by_command, text)

    def _showline_without_repetition(
        self, state: PlayerState, by_command: bool, text: str
    ) -> Tuple[PlayerState, bool]:
        if (
            state.pointer,
            text,
            efablogger.get_counter(),
        ) == state.last_shown_line and not by_command:
            return state, False
        if efablogger.say(text, type_of_msg=efablogger.NORMAL):
            state = replace(
                state,
                last_shown_line=(
                    state.pointer,
                    text,
                    efablogger.get_counter(),
                ),
            )
            return state, True
        return state, False

    def _line_to_show(self, state: PlayerState) -> str:
        return self._get_line(state, self.options.show_subst)

    def _line_to_say(self, state: PlayerState) -> str:
        return self._get_line(state, self.options.apply_subst)

    def _get_line(self, state: PlayerState, substitute: bool) -> str:
        line = state.lines[state.pointer]
        return self._substitutions.apply(line) if substitute else line

    @_state
    def first(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._movement_aux(state, _FIRST)

    @_state
    def previous(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._movement_aux(state, _PREV)

    @_state
    def next(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._movement_aux(state, _NEXT)

    @_state
    def last(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._movement_aux(state, _LAST)

    def _movement_aux(
        self, state: PlayerState, action: str
    ) -> Tuple[PlayerState, bool]:
        sequence = self.options.sequence_mode
        forward = action in [_NEXT, _LAST]
        if sequence.empty(state):
            efablogger.say(sequence.msg_empty, type_of_msg=efablogger.INFO)
            return state, False
        elif forward and sequence.eof(state):
            efablogger.say(sequence.msg_eof, type_of_msg=efablogger.INFO)
            return state, False
        elif not forward and sequence.bof(state):
            efablogger.say(sequence.msg_bof, type_of_msg=efablogger.INFO)
            return state, False
        else:
            msg = None
            if action == _PREV:
                msg = _BACK_ONE_LINE
            elif action == _FIRST:
                msg = sequence.msg_first
            elif action == _LAST:
                msg = sequence.msg_last
            if msg is not None:
                efablogger.say(msg, type_of_msg=efablogger.INFO)
            f = getattr(sequence, action)
            return self._go(state, pointer=f(state)), True

    @_state
    def go_random(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        efablogger.say(_CHOOSING_RANDOM, type_of_msg=efablogger.INFO)
        new_state = self._go(state, SequenceRandom.next(state))
        return new_state, new_state.pointer != state.pointer

    @_state
    def find(
        self,
        state: PlayerState,
        search: Optional[StoredSearch] = None,
        starting_from: Optional[int] = None,
        forward=True,
    ) -> Tuple[PlayerState, bool]:
        return self._find(state, search, starting_from, forward)

    def _find(
        self,
        state: PlayerState,
        search: Optional[StoredSearch] = None,
        starting_from: Optional[int] = None,
        forward=True,
    ) -> Tuple[PlayerState, bool]:
        search = search or state.stored_search
        if search is None:
            return state, False
        if starting_from is None:
            starting_from = state.pointer
        if forward:
            _range = range(starting_from, len(state.lines))
        else:
            _range = range(starting_from, -1, -1)
        state, success = self._find_aux(state, search, _range)
        if success:
            return state, True
        else:
            efablogger.say(
                _NOT_FOUND % search.expression, type_of_msg=efablogger.INFO
            )
            return state, False

    def _find_aux(
        self, state: PlayerState, search: StoredSearch, _range: range
    ) -> Tuple[PlayerState, bool]:
        for i in _range:
            if search.pattern.search(state.lines[i]):
                if i == state.pointer:
                    msg = _FOUND_SAME
                else:
                    msg = _FOUND
                efablogger.say(
                    msg % (search.expression, i + 1),
                    type_of_msg=efablogger.INFO,
                )
                state = self._go(state, i)
                state = replace(state, stored_search=search)
                return state, True
        else:
            return state, False

    @_state
    def find_next(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._find(state, starting_from=state.pointer + 1)

    @_state
    def find_previous(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return self._find(
            state, starting_from=state.pointer - 1, forward=False
        )

    @_state
    def go_modified(
        self, state: PlayerState, forward: bool
    ) -> Tuple[PlayerState, bool]:
        if not state.modified_lines:
            efablogger.say(SequenceModified.msg_empty, efablogger.INFO)
            return state, False
        aux = self._go_modified_aux(state, forward)
        if aux.hit_limit:
            if aux.end_of_sequence:
                efablogger.say(aux.msg_end_of_sequence, efablogger.INFO)
            else:
                efablogger.say(aux.msg_not_end_of_sequence, efablogger.INFO)
            return state, False
        else:
            efablogger.say(aux.msg_skipping, efablogger.INFO)
            state = self._go(state, aux.next())
            return state, True

    @staticmethod
    def _go_modified_aux(state, forward):
        class AUX:
            pass

        aux = AUX()
        if forward:
            aux.hit_limit = SequenceModified.eof(state)
            aux.end_of_sequence = state.pointer == state.modified_lines[-1]
            aux.msg_end_of_sequence = SequenceModified.msg_eof
            aux.msg_not_end_of_sequence = _NO_MODIFIED_AFTER
            aux.msg_skipping = _SKIPPING_NEXT_MODIFIED
            aux.next = lambda: SequenceModified.next(state)
        else:
            aux.hit_limit = SequenceModified.bof(state)
            aux.end_of_sequence = state.pointer == state.modified_lines[0]
            aux.msg_end_of_sequence = SequenceModified.msg_bof
            aux.msg_not_end_of_sequence = _NO_MODIFIED_BEFORE
            aux.msg_skipping = _SKIPPING_PREV_MODIFIED
            aux.next = lambda: SequenceModified.previous(state)
        return aux

    @_state
    def refresh_line(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return state, self._refresh_line(state)

    def _refresh_line(self, state: PlayerState) -> bool:
        return (
            state.line_being_read is not None
            and state.line_being_read != self._line_to_say(state)
        )

    def substitution_rules_changed(self) -> None:
        state = self._getstate()
        if state.text is None:
            pass
        elif self._refresh_line(state):
            state = self._new_substitution_apply_to_this_line(state)
        else:
            efablogger.say(_SUBST_DONT_APPLY, type_of_msg=efablogger.INFO)
        self._putstate(state)

    def _new_substitution_apply_to_this_line(
        self, state: PlayerState
    ) -> PlayerState:
        running = self.running_and_not_paused()
        restart = (
            not self.running()
            and self.options.restart_after_substitution_change
        )
        if running or restart:
            efablogger.say(_SUBST_APPLY, type_of_msg=efablogger.INFO)
            state, running = self._read_substitution_message(state)
            if running:
                state = self._update_player(state)
            else:
                state = self._restart(state)
        else:
            efablogger.say(_SUBST_ON_RESTART, type_of_msg=efablogger.INFO)
            if self.running_and_paused():
                efablogger.say(_SUBST_BUT_PAUSED, type_of_msg=efablogger.INFO)
        return state

    def _read_substitution_message(
        self, state: PlayerState
    ) -> Tuple[PlayerState, bool]:
        msg = efabtracking.get_message(
            self._feedback_messages,
            self.options.feedback_mode,
            "subst-changed",
        )
        if msg:
            state = self._stop(state)
            while (
                self.playing_feedback()
            ):  # It should probably be False, but just in case
                time.sleep(0.1)
            _BasicPlayer(lines=msg, options=self.options).play()
            return state, False
        else:
            return state, True

    def schedule_delayed_reload(self, loader):
        efablogger.say(_RELOAD_ON_RESTART, type_of_msg=efablogger.INFO)
        spoken_msg = efabtracking.get_message(
            self._feedback_messages,
            self.options.feedback_mode,
            "reload-delayed",
        )
        if spoken_msg:
            _BasicPlayer(lines=spoken_msg, options=self.options).play()
        state = self._getstate()
        state = replace(state, reload_scheduled=True, loader=loader)
        self._putstate(state)

    @_state
    def reload_scheduled(self, state: PlayerState) -> Tuple[PlayerState, bool]:
        return state, state.reload_scheduled

    def playing_feedback(self) -> bool:
        return self._updater.playing_feedback()

    def stop_feedback(self) -> None:
        self._updater.stop_feedback()

    def stop_update(self) -> None:
        self._updater.stop_update()


class _Updater:

    # This is a friendly class, and has access to the attributes of Player.
    # Its funtionality could be part of Player, but we create a separate class
    # to avoid cluttering too much the main class.

    def __init__(self, player: Player):
        self._player = player
        self._thread = None
        self._thread_started = threading.Event()
        self._update_to_restart = False
        self._abort_update = False
        self._data = _Store()
        self._feedback_player = _Store()

    def run(self, state: PlayerState, text: str, lines: List[str]) -> None:
        if self.running():
            self._restart_update(text, lines)
        else:
            self._data.put((text, lines))
            self._thread_started.clear()
            self._thread = start_daemon(lambda: self._run(state))
            self._thread_started.wait()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self, state: PlayerState) -> None:
        # Acquire lock on player to exclude command interpretation while doing
        # an update. See efabcore module for the competing lock acquisition
        # this one is intended to preclude.
        with self._player.lock:
            self.__run(state)

    def __run(self, state: PlayerState) -> None:
        self._thread_started.set()
        player_stopped = False
        changed_again = False

        player_running_and_not_paused = self._player.running_and_not_paused()

        feedback_messages = self._player._feedback_messages
        options = self._player.options

        baseline = efabtracking.baseline(
            state, player_running_and_not_paused, feedback_messages, options
        )

        while not self._data.empty():
            text, lines = self._data.get()
            (
                modified_lines,
                logs,
                spoken_feedback,
                jump_to,
                action,
            ) = efabtracking.get_feedback_and_action(
                baseline, text, lines, changed_again
            )
            for line in logs:
                efablogger.say(line, type_of_msg=efablogger.INFO)
            if spoken_feedback:
                player = _BasicPlayer(
                    lines=spoken_feedback, options=self._player.options
                )
                self._feedback_player.put(player)
                if player_running_and_not_paused and not player_stopped:
                    _stop_espeak(state.espeak, False)
                    player_stopped = True
                player.play()
            else:
                self._feedback_player.put(None)
            if self._abort_update:
                self._abort_update = False
                self._player._putstate(state)
                return
            elif self._update_to_restart:
                changed_again = True
                self._update_to_restart = False
            else:
                self._update_state(
                    state,
                    text,
                    lines,
                    modified_lines,
                    jump_to,
                    action
                )
                self._feedback_player.get(block=False)

    def stop_feedback(self, block=False) -> None:
        player = self._feedback_player.get(block=block)
        if player is not None and player.running():
            player.stop()

    def playing_feedback(self) -> bool:
        player = self._feedback_player.get(block=False)
        if player is not None:
            self._feedback_player.put(player)
            return player.running()
        else:
            return False

    def _update_state(
        self,
        state: PlayerState,
        text: str,
        lines: List[str],
        modified_lines: List[int],
        jump_to: Optional[int],
        action: efabtracking.Action,
    ) -> None:
        state = replace(
            state, text=text, lines=lines, modified_lines=modified_lines
        )

        if jump_to is not None:
            state = self._player._go(state, jump_to)
            if self._player.options.stop_after_current_line:
                self._player.options.stop_after_current_line = False
                self._player.options.log("stop-after-current-line")

        if action == efabtracking.STOP:
            state = self._player._stop(state)
        elif action == efabtracking.RESTART:
            state = self._player._restart(state)

        self._player._putstate(state)

    def _restart_update(self, text: str, lines: List[str]) -> None:
        self._data.put((text, lines))
        self._update_to_restart = True
        self.stop_feedback(block=True)

    def stop_update(self) -> None:
        if self.running():
            self._abort_update = True
            self.stop_feedback(block=True)
