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


if TYPE_CHECKING:
    _ = gettext.gettext


def sequence_modes_dict():
    return {
        "normal": SequenceNormal,
        "modified": SequenceModified,
        "random": SequenceRandom,
    }


def sequence_mode(name):
    return sequence_modes_dict()[name]


def default_sequence_mode_key():
    return "normal"


class StateProtocol(Protocol):
    pointer: int
    text: Optional[str]
    lines: List[str]
    modified_lines: List[int]
    eol: bool
    said_anything: bool


class Sequence(Protocol):
    msg_bof: str
    msg_eof: str
    msg_first: str
    msg_last: str
    msg_empty: Optional[str]
    empty: Callable[[StateProtocol], bool]
    first: Callable[[StateProtocol], int]
    last: Callable[[StateProtocol], int]
    bof: Callable[[StateProtocol], bool]
    eof: Callable[[StateProtocol], bool]
    next: Callable[[StateProtocol], Optional[int]]
    previous: Callable[[StateProtocol], Optional[int]]


class SequenceNormal(Sequence):
    msg_bof = _("This is the beginning of the text.")
    msg_eof = _("This is the end of the text.")
    msg_first = _("Jumping back to the beginning of the text.")
    msg_last = _("Jumping forward to the end of the text.")
    msg_empty = None

    @staticmethod
    def empty(state):
        return False

    @staticmethod
    def first(state):
        return 0

    @staticmethod
    def last(state):
        return len(state.lines) - 1

    @staticmethod
    def bof(state):
        return state.pointer == 0

    @staticmethod
    def eof(state):
        return state.pointer == len(state.lines) - 1

    @staticmethod
    def next(state):
        return (
            state.pointer + 1
            if state.pointer + 1 < len(state.lines)
            else None
        )

    @staticmethod
    def previous(state):
        return (
            state.pointer - 1 if state.pointer > 0 else None
        )


class SequenceModified(Sequence):
    msg_bof = _("This is the first modified line.")
    msg_eof = _("This is the last modified line.")
    msg_first = _("Jumping back to the first modified line.")
    msg_last = _("Jumping forward to the last modified line.")
    msg_empty = _("There are no modified lines.")

    @staticmethod
    def empty(state):
        return len(state.modified_lines) == 0

    @staticmethod
    def first(state):
        return (
            state.modified_lines[0]
            if state.modified_lines
            else SequenceNormal.first(state)
        )

    @staticmethod
    def last(state):
        return (
            state.modified_lines[-1]
            if state.modified_lines
            else SequenceNormal.last(state)
        )

    @staticmethod
    def bof(state):
        return (
            not state.modified_lines
            or state.pointer <= state.modified_lines[0]
        )

    @staticmethod
    def eof(state):
        return (
            not state.modified_lines
            or state.pointer >= state.modified_lines[-1]
        )

    def next(state):
        return (
            (
                [x for x in state.modified_lines if x > state.pointer]
                + [state.pointer]
            )[0]
        )

    def previous(state):
        return (
            (
                [state.pointer]
                + [x for x in state.modified_lines if x < state.pointer]
                )[-1]
        )


class SequenceRandom(Sequence):
    msg_bof = _("This is the beginning of the random reading history.")
    msg_eof = _("This is the end of the random reading history.")
    msg_first = _(
        "Jumping back to the beginning of the random reading " "history."
    )
    msg_last = _("Jumping forward to the end of the random reading history.")
    msg_empty = None

    @staticmethod
    def empty(state):
        return False

    @staticmethod
    def bof(state):
        return False

    @staticmethod
    def eof(state):
        return False

    _HISTORY_MAX_LENGTH = 100  # TODO: add a runtime-option for this?
    _history: List[int] = []
    _index = 0

    _lock = threading.RLock()

    @classmethod  # class SequenceRandom
    def first(cls, state: StateProtocol) -> int:
        with cls._lock:
            h = cls._history
            return h[0] if h else cls.next(state)

    @classmethod  # class SequenceRandom
    def last(cls, state: StateProtocol) -> int:
        with cls._lock:
            h = cls._history
            return h[-1] if h else cls.next(state)

    @classmethod  # class SequenceRandom
    def next(cls, state: StateProtocol) -> int:
        with cls._lock:
            h = cls._history
            if not h or cls._index == len(h) - 1:
                where = randint(0, len(state.lines) - 1)
                h.append(where)
                if len(h) > cls._HISTORY_MAX_LENGTH:
                    del h[0]
                cls._index = len(h) - 1
            else:
                cls._index += 1
                where = h[cls._index]
            return where

    @classmethod  # class SequenceRandom
    def previous(cls, state: StateProtocol) -> int:
        with cls._lock:
            h = cls._history
            if not h or cls._index == 0:
                where = randint(0, len(state.lines) - 1)
                h.insert(0, where)
                if len(h) > cls._HISTORY_MAX_LENGTH:
                    del h[-1]
            else:
                cls._index -= 1
                where = h[cls._index]
            return where
