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

from efabseq import SequenceNormal, SequenceRandom
from itertools import product

from efabtracking import *


if __name__ == "__main__":

    # This is the embryo of a proper collection of tests for efabulor. For the
    # time being we only test the get_feedback_and_action() function in the
    # efabtracking module, with a brute force approach: check predicates on
    # the output for assorted combinations of the input parameters.

    # TODO: gradually add tests to the rest of the modules, and maybe use some
    # standard framework such as unittest and/or improve the reporting.

    # TODO: we are not actually checking the combination of the previous
    # modified lines with the new ones when changed_again is True.

    # TODO: check whether the set of command line/runtime options affecting
    # the efabtracking module can be improved.

    class State:
        pass

    state = State()

    class Opt:
        pass

    options = Opt()

    feedback_messages = {k: k for k in message_levels.keys()}

    NEWLEN = [2, 4, 5, 6, 10, 11, 15]
    LEN = NEWLEN[-3]
    MAXLEN = NEWLEN[-1]
    POINTER = NEWLEN[-4]
    CHANGED_LINES = [
        (),
        (0,), (2,), (3,), (4,), (5,), (6,),
        (0, 7,), (2, 7,), (3, 7,), (4, 7,), (5, 7), (6, 7,),
    ]

    RANDOM_INPUT = [str(randint(0, LEN)) for x in range(MAXLEN)]

    state.lines = [x for x in RANDOM_INPUT[:LEN]]
    state.text = "\n".join(state.lines)
    state.pointer = POINTER
    state.said_anything = True

    state.modified_lines = []

    # TODO: systematize the adding of test dimensions
    total_cases = 1

    _newlen = NEWLEN
    total_cases *= len(_newlen)

    _changed_lines = CHANGED_LINES
    total_cases *= len(_changed_lines)

    _changed_again = [False, True]
    total_cases *= len(_changed_again)

    _player_was_running_and_not_paused = [False, True]
    total_cases *= len(_player_was_running_and_not_paused)

    _tracking_mode = [
        BACKWARD_TRACKING,
        FORWARD_TRACKING,
        RESTART_FROM_BEGINNING,
        NO_TRACKING,
    ]
    total_cases *= len(_tracking_mode)

    i = 0

    _feedback_mode = [NO_FEEDBACK, MINIMUM_FEEDBACK, FULL_FEEDBACK]
    total_cases *= len(_feedback_mode)

    _sequence_mode = [SequenceNormal, SequenceModified, SequenceRandom]
    total_cases *= len(_sequence_mode)

    _eol = [False, True]
    total_cases *= len(_eol)

    _restart_on_touch = [False, True]
    total_cases *= len(_restart_on_touch)

    _restart_after_change = [False, True]
    total_cases *= len(_restart_after_change)

    _restarting_message_when_not_playing = [False, True]
    total_cases *= len(_restarting_message_when_not_playing)

    def ifthen(a, b):
        return not a() or b()

    start_time = time.time()

    cases = 0
    tests = 0

    for (
        newlen,
        changed_lines,
        changed_again,
        player_was_running_and_not_paused,
        tracking_mode,
        feedback_mode,
        sequence_mode,
        eol,
        restart_on_touch,
        restart_after_change,
        restarting_message_when_not_playing,
    ) in product(
        _newlen,
        _changed_lines,
        _changed_again,
        _player_was_running_and_not_paused,
        _tracking_mode,
        _feedback_mode,
        _sequence_mode,
        _eol,
        _restart_on_touch,
        _restart_after_change,
        _restarting_message_when_not_playing,
    ):

        cases += 1

        if not (cases % 84):
            print(
                "Testing case %s (%d%%)" % (cases, 100 * cases / total_cases),
                end="\r",
            )

        lines = [x for x in RANDOM_INPUT[:newlen]]
        text = "\n".join(lines)

        changed_lines = [x for x in changed_lines if x < newlen]
        for line in changed_lines:
            lines[line] = "x"

        options.feedback_mode = feedback_mode
        options.tracking_mode = tracking_mode
        options.sequence_mode = sequence_mode
        options.restart_on_touch = restart_on_touch
        options.restart_after_change = restart_after_change
        options.restarting_message_when_not_playing = (
            restarting_message_when_not_playing
        )
        state.eol = eol

        _baseline = baseline(
            state, player_was_running_and_not_paused, feedback_messages,
            options
        )

        (
            modified_lines,
            log,
            spoken_feedback,
            jump_to,
            action,
        ) = get_feedback_and_action(
            _baseline, text, lines, changed_again
        )

        tests = 0

        def _failed(msg):
            global tests

            print()
            print("Failed: ", msg)
            print()
            print("old lines", state.lines)
            print("new lines", lines)
            print("pointer: ", state.pointer)
            print("newlen: ", newlen)
            print("changed lines: ", changed_lines)
            print("changed again: ", changed_again)
            print("player was running: ", player_was_running_and_not_paused)
            tmp = {v: k for k, v in feedback_modes_dict().items()}
            print("feedback: ", tmp[feedback_mode])
            tmp = {v: k for k, v in tracking_modes_dict().items()}
            print("tracking_mode: ", tmp[tracking_mode])
            tmp = {SequenceNormal: "normal", SequenceModified: "modified"}
            print("sequence: ", tmp[sequence_mode])
            print("restart on touch: ", restart_on_touch)
            print("restart after change: ", restart_after_change)
            print(
                "restarting message when not playing: ",
                restarting_message_when_not_playing,
            )
            print("eol: ", eol)
            print()
            print("modified lines: ", modified_lines)
            print("logs: ", log)
            print("feedback: ", spoken_feedback)
            print("go: ", jump_to)
            print("action: ", action)
            print()
            print()
            sys.exit(DEFAULT_ERROR_RETURNCODE)

        tests += 1
        ifthen(
            lambda: (
                tracking_mode == NO_TRACKING
                and not newlen <= state.pointer
            ),
            lambda: jump_to is None
        ) or _failed("No jump if not tracking, unless the file got too short")

        tests += 1
        ifthen(
            lambda: changed_lines,
            lambda: modified_lines
        ) or _failed("Report when there are modified lines")

        tests += 1
        ifthen(
            lambda: (
                not modified_lines
                and newlen <= state.pointer
                and tracking_mode != RESTART_FROM_BEGINNING
            ),
            lambda: (
                jump_to == newlen - 1
                and action == STOP
            )
        ) or _failed(
            "Go to the last line and stop if no modified lines and the file "
            "got too short, unless tracking_mode == RESTART_FROM_BEGINNING"
        )

        tests += 1
        ifthen(
            lambda: (
                newlen <= state.pointer
                and not modified_lines
                and tracking_mode == RESTART_FROM_BEGINNING
                and (
                    restart_after_change
                    or restart_on_touch
                )
            ),
            lambda: (
                jump_to == 0
                and action == RESTART
            )
        ) or _failed(
            "Go to the first line and restart if no modified lines and the "
            "file got too short and tracking_mode == RESTART_FROM_BEGINNING "
            "and restart_after_change or restart_on_touch"
        )

        tests += 1
        ifthen(
            lambda: (
                not modified_lines
                and newlen > state.pointer
                and not (
                    tracking_mode == RESTART_FROM_BEGINNING
                    and restart_on_touch
                )
            ),
            lambda: jump_to is None,
        ) or _failed(
            "No jump if no modified_lines lines (except if the file got too "
            "short or sequence_mode=RESTART_FROM_BEGINNING and "
            "restart_on_touch)"
        )

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and modified_lines[0] <= (
                    state.pointer + (1 if state.eol else 0)
                ) and tracking_mode == BACKWARD_TRACKING
            ),
            lambda: jump_to == modified_lines[0],
        ) or _failed("Jump to first modified line when backward tracking")

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and tracking_mode == FORWARD_TRACKING
                and not (
                    player_was_running_and_not_paused
                    and sequence_mode == SequenceModified
                    and modified_lines[0] > state.pointer
                )
            ),
            lambda: jump_to == modified_lines[0],
        ) or _failed(
            "Jump to first modified line when forward tracking, except if "
            "sequence_mode==modified and the player was playing and the first "
            "modified line is after the current one"
        )

        tests += 1
        ifthen(
            lambda: (
                tracking_mode == RESTART_FROM_BEGINNING
                and (
                    modified_lines
                    or restart_on_touch
                    or newlen <= state.pointer
                )
            ),
            lambda: jump_to == 0,
        ) or _failed(
            "Jump to first line if tracking is set to ‘restart from beginning’"
        )

        tests += 1
        ifthen(
            lambda: (
                sequence_mode is SequenceModified
                and modified_lines
                and modified_lines[0] > state.pointer
                and tracking_mode != RESTART_FROM_BEGINNING
                and player_was_running_and_not_paused
            ),
            lambda: jump_to is None,
        ) or _failed(
            "No jump when sequence=modified and first change is after current "
            "line, and the player is running"
        )

        tests += 1
        ifthen(
            lambda: (
                restart_on_touch
                and newlen > state.pointer
            ),
            lambda: action == RESTART
        ) or _failed(
            "Restart if file is touched and restart_on_touch unless the "
            "file only got too short"
        )

        tests += 1
        ifthen(
            lambda: (
                restart_after_change
                and jump_to is not None
                and newlen > state.pointer
            ),
            lambda: action == RESTART
        ) or _failed(
            "Restart if file jump and restart_after_change unless the "
            "file got too short"
        )

        tests += 1
        ifthen(
            lambda: (
                newlen <= state.pointer
                and not modified_lines
                and tracking_mode != RESTART_FROM_BEGINNING
            ),
            lambda: action == STOP
        ) or _failed(
            "Stop the player if the file got too short and there are no "
            "modified lines and tracking_mode != RESTART_FROM_BEGINNING"
        )

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and jump_to is not None
                and restart_after_change
                and newlen > state.pointer
            ),
            lambda: action == RESTART
        ) or _failed(
            "Always restart when there is a jump due to changes and "
            "restart_after_change, unless the file got too short"
        )

        tests += 1
        ifthen(
            lambda: feedback_mode == NO_FEEDBACK, lambda: not spoken_feedback
        ) or _failed("No feedback if feedback-mode=none")

        tests += 1
        ifthen(
            lambda: feedback_mode == MINIMUM_FEEDBACK,
            lambda: all(
                message_levels[x] == MINIMUM_FEEDBACK
                or x == "changes-here" and not restart_after_change
                or x == "file-too-short" and newlen <= state.pointer
                for x in spoken_feedback
            ),
        ) or _failed("Only minimum feedback if feedback-mode=minimum")

        tests += 1
        ifthen(
            lambda: (
                not modified_lines
                and feedback_mode == FULL_FEEDBACK
                and not changed_again
                and newlen == len(state.lines)
            ),
            lambda: "no-changes" in spoken_feedback,
        ) or _failed("Report no changes")

        tests += 1
        ifthen(
            lambda: (
                changed_again
                and feedback_mode == FULL_FEEDBACK
                and lines == state.lines
            ),
            lambda: "changes-reverted" in spoken_feedback,
        ) or _failed("Report changes reverted")

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and modified_lines[0] < state.pointer
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: "changes-before" in spoken_feedback,
        ) or _failed("Report changes before")

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and modified_lines[0] == state.pointer
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: "changes-here" in spoken_feedback,
        ) or _failed("Report changes here")

        tests += 1
        ifthen(
            lambda: "changes-here" in spoken_feedback,
            lambda: feedback_mode == FULL_FEEDBACK or action != RESTART
        ) or _failed(
            "Do not report changes-here, unless feedback_mode==FULL_FEEDBACK "
            "or not restarting"
        )

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and modified_lines[0] > state.pointer
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: any(
                x in spoken_feedback for x in ["changes-after", "changes-next"]
            ),
        ) or _failed("Report changes after/next")

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and modified_lines[0] == state.pointer + 1
                and eol
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: "changes-next" in spoken_feedback,
        ) or _failed("Report changes next")

        tests += 1
        ifthen(
            lambda: (
                len(modified_lines) > 1
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: "many-changes" in spoken_feedback,
        ) or _failed("Report when there are many modified lines")

        tests += 1
        ifthen(
            lambda: (
                newlen <= state.pointer
                and feedback_mode == FULL_FEEDBACK
            ),
            lambda: "file-too-short" in spoken_feedback
        ) or _failed("Report if the file got too short")

        def _restarting_message_when_not_playing_aux():
            a = any(
                x in spoken_feedback
                for x in [
                    "restarting",
                    "jumping-back",
                    "continuing",
                    "jumping-forward",
                ]
            )
            return a == options.restarting_message_when_not_playing

        tests += 1
        ifthen(
            lambda: (
                action == RESTART
                and not player_was_running_and_not_paused
                and feedback_mode != NO_FEEDBACK
                and tracking_mode != RESTART_FROM_BEGINNING
            ),
            _restarting_message_when_not_playing_aux,
        ) or _failed("Obey restarting_message_when_not_playing option")

        tests += 1
        ifthen(
            lambda: (
                modified_lines
                and jump_to is not None and jump_to < state.pointer
                and jump_to == modified_lines[0]
                and feedback_mode != NO_FEEDBACK
                and tracking_mode != RESTART_FROM_BEGINNING
                and (
                    player_was_running_and_not_paused
                    or restarting_message_when_not_playing
                )
            ),
            lambda: "jumping-back" in spoken_feedback,
        ) or _failed("Report when jumping back")

        tests += 1
        ifthen(
            lambda: (
                action == RESTART
                and jump_to is not None and jump_to == state.pointer
                and feedback_mode != NO_FEEDBACK
                and tracking_mode != RESTART_FROM_BEGINNING
                and (
                    player_was_running_and_not_paused
                    or restarting_message_when_not_playing
                )
            ),
            lambda: "restarting" in spoken_feedback,
        ) or _failed("Report when restarting")

        tests += 1
        ifthen(
            lambda: (
                action == RESTART
                and eol
                and jump_to is not None and jump_to == state.pointer + 1
                and feedback_mode != NO_FEEDBACK
                and tracking_mode != RESTART_FROM_BEGINNING
                and (
                    player_was_running_and_not_paused
                    or restarting_message_when_not_playing
                )
            ),
            lambda: "continuing" in spoken_feedback,
        ) or _failed("Report when continuing")

        tests += 1
        ifthen(
            lambda: (
                jump_to is not None
                and (
                    jump_to > state.pointer + 1
                    or jump_to == state.pointer + 1 and not eol
                ) and feedback_mode != NO_FEEDBACK
                and (
                    player_was_running_and_not_paused
                    or restarting_message_when_not_playing
                )
            ),
            lambda: "jumping-forward" in spoken_feedback,
        ) or _failed("Report when jumping forward")

        tests += 1
        ifthen(
            lambda: (
                action == RESTART
                and tracking_mode == RESTART_FROM_BEGINNING
                and feedback_mode != NO_FEEDBACK
            ),
            lambda: "starting-again" in spoken_feedback,
        ) or _failed("Report when starting again from the beginning")

        tests += 1
        ifthen(
            lambda: action != RESTART,
            lambda: (
                "restarting" not in spoken_feedback
                and "continuing" not in spoken_feedback
                and "starting-again" not in spoken_feedback
            ),
        ) or _failed("Do not report restarting actions if not restarting")

        tests += 1
        if any(spoken_feedback.count(x) > 1 for x in spoken_feedback):
            _failed("Repeated keys in spoken feedback")

        tests += 1
        if feedback_mode == MINIMUM_FEEDBACK and len(spoken_feedback) > 1:
            _failed("No more than one feedback message with minimum feedback")

    print(
        "Completed %s tests on %s different cases in %f seconds, and found "
        "no errors!" % (tests, total_cases, time.time() - start_time)
    )
