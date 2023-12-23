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

from efabseq import SequenceModified, Sequence, StateProtocol


if TYPE_CHECKING:
    _ = gettext.gettext


_TrackingMode = int

NO_TRACKING = 0
BACKWARD_TRACKING = 1
FORWARD_TRACKING = 2
RESTART_FROM_BEGINNING = 3


def tracking_modes_dict():
    return {
        "none": NO_TRACKING,
        "backward": BACKWARD_TRACKING,
        "forward": FORWARD_TRACKING,
        "restart": RESTART_FROM_BEGINNING,
    }


def tracking_mode(name):
    return tracking_modes_dict()[name]


def default_tracking_mode_key():
    return "backward"


_FeedbackMode = int

NO_FEEDBACK = 0
MINIMUM_FEEDBACK = 1
FULL_FEEDBACK = 2


def feedback_modes_dict():
    return {
        "none": NO_FEEDBACK,
        "minimum": MINIMUM_FEEDBACK,
        "full": FULL_FEEDBACK,
    }


def feedback_mode(name):
    return feedback_modes_dict()[name]


def default_feedback_mode_key():
    return "minimum"


message_levels = {
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


def feedback_message_keys():
    return message_levels.keys()


# The Baseline class represents a 'snapshot' of the player's state at the
# moment a new version of the input text was loaded, along with information
# that will be needed to create the tracking event.
@dataclass
class Baseline:
    state: StateProtocol
    feedback_messages: Dict[str, str]
    feedback_mode: _FeedbackMode
    tracking_mode: _TrackingMode
    sequence_mode: Sequence
    restart_after_change: bool
    restarting_message_when_not_playing: bool
    restart_on_touch: bool
    player_was_running_and_not_paused: bool


Action = int


# Values for _TmpData.action

NO_ACTION = 0
STOP = 1
RESTART = 2


# We use the _TmpData helper class to store information about the transition
# between the old text and the new text.
@dataclass
class _TmpData:
    baseline: Baseline
    text: str
    lines: List[str]
    changed_again: bool
    blank_areas_changed: bool = False
    jump_to: Optional[int] = None
    action: Action = NO_ACTION
    modified_lines: List[int] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    spoken_feedback: List[str] = field(default_factory=list)


class _OptionsProtocol(Protocol):
    feedback_mode: _FeedbackMode
    tracking_mode: _TrackingMode
    sequence_mode: Sequence
    # TODO: annotate efabrto and check these annotations
    restart_after_change: bool
    restarting_message_when_not_playing: bool
    restart_on_touch: bool


def baseline(
    state: StateProtocol,
    player_running: bool,
    feedback_messages: Dict[str, str],
    options: _OptionsProtocol
) -> Baseline:
    return Baseline(
        state,
        feedback_messages,
        options.feedback_mode,
        options.tracking_mode,
        options.sequence_mode,
        options.restart_after_change,
        options.restarting_message_when_not_playing,
        options.restart_on_touch,
        player_running,
    )


_TrackingEvent = Tuple[List[int], List[str], List[str], Optional[int], Action]


def get_feedback_and_action(
    baseline: Baseline,
    text: str,
    lines: List[str],
    changed_again: bool,
) -> _TrackingEvent:

    tmp_data = _TmpData(baseline, text, lines, changed_again)

    tmp_data.blank_areas_changed = _blank_areas_changed(tmp_data)
    tmp_data.modified_lines = _modified_lines(tmp_data)
    tmp_data.jump_to, tmp_data.action = _get_jump_and_action(tmp_data)

    tmp_data.logs = _logs(tmp_data)

    tmp_data.spoken_feedback = _get_basic_spoken_feedback(tmp_data)

    if (
        tmp_data.action == NO_ACTION
        and baseline.player_was_running_and_not_paused
        and len(tmp_data.spoken_feedback) > 0
    ):
        tmp_data.action = RESTART

    tmp_data.spoken_feedback.extend(_feedback_for_action_taken(tmp_data))

    return (
        tmp_data.modified_lines,
        tmp_data.logs,
        tmp_data.spoken_feedback,
        tmp_data.jump_to,
        tmp_data.action,
    )


def _blank_areas_changed(tmp_data: _TmpData) -> bool:
    assert tmp_data.baseline.state.text is not None
    old_blank_areas = re.findall(r"(\s+?)\n+", tmp_data.baseline.state.text)
    blank_areas = re.findall(r"(\s+?)\n+", tmp_data.text)
    return old_blank_areas != blank_areas


def _modified_lines(tmp_data: _TmpData) -> List[int]:

    modified_lines = _modified_lines_aux(
        tmp_data.baseline.state.lines, tmp_data.lines
    )

    newlen = len(tmp_data.lines)
    if newlen < len(tmp_data.baseline.state.lines):
        modified_lines = [n for n in modified_lines if n < newlen]
    if tmp_data.baseline.sequence_mode is SequenceModified:
        # state.modified_lines still contains the list of modified
        # lines from the previous text's version.
        tmp_modified_lines = [
            x
            for x in tmp_data.baseline.state.modified_lines
            if x > tmp_data.baseline.state.pointer and x < len(tmp_data.lines)
        ]
        if tmp_modified_lines:
            modified_lines = sorted(
                list(set(modified_lines + tmp_modified_lines))
            )
    return modified_lines


def _modified_lines_aux(a: List[str], b: List[str]) -> List[int]:
    modified_lines: List[int] = []
    s = SequenceMatcher(None, a, b, autojunk=False)
    last_a = 0
    last_b = 0
    for block in s.get_matching_blocks():
        if block.b > last_b:  # replacement/insertion
            modified_lines.extend(range(last_b, block.b))
        elif block.a > last_a:  # deletion
            modified_lines.append(block.b)
        last_a = block.a + block.size
        last_b = block.b + block.size
    return modified_lines


def _logs(tmp_data: _TmpData) -> List[str]:
    logs = []
    logs.extend(_report_changed_again(tmp_data))
    if len(tmp_data.lines) == 0:
        logs.append(_("The input file is empty."))
        return logs
    logs.extend(_report_blank_areas_changed(tmp_data))
    logs.extend(_report_length_change(tmp_data))
    if not tmp_data.modified_lines:
        if len(tmp_data.lines) == len(tmp_data.baseline.state.lines):
            logs.extend(_report_no_modified_lines(tmp_data))
            return logs
    else:
        logs.extend(_show_modified_lines_and_action(tmp_data))

    if tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
        logs.append(_("Restarting from the beginning."))

    return logs


def _report_changed_again(tmp_data: _TmpData) -> List[str]:
    if tmp_data.changed_again:
        return [
            _("The input file changed again on disk."),
            _(
                "Reporting changes again (may include previously reported "
                "changes)."
            ),
        ]
    else:
        return []


def _report_blank_areas_changed(tmp_data: _TmpData) -> List[str]:
    if tmp_data.blank_areas_changed:
        return [_("Blank areas of the input file have changed.")]
    else:
        return []


def _report_length_change(tmp_data: _TmpData) -> List[str]:
    oldlen = len(tmp_data.baseline.state.lines)
    newlen = len(tmp_data.lines)
    if newlen < oldlen:
        return [
            _("The text was shortened from %s to %s line(s).")
            % (oldlen, newlen)
        ]
    elif newlen > oldlen:
        return [
            _("The text was extended from %s to %s lines.") % (oldlen, newlen)
        ]
    else:
        return []


def _report_no_modified_lines(tmp_data: _TmpData) -> List[str]:
    if not tmp_data.changed_again:
        return [_("No changes to the text were detected.")]
    else:
        return [_("The latest changes have been reverted.")]


_ACTION_MSG_1 = _(
    "Changes were detected at lines: %s (current line is: " "%s)."
)
_ACTION_MSG_2 = _(
    "Changes were detected at lines: %s; the player will jump "
    "back from line %s."
)
_ACTION_MSG_3 = _(
    "Changes were detected at lines: %s; the player will "
    "restart at line %s."
)
_ACTION_MSG_4 = _(
    "Changes were detected at lines: %s; the player will "
    "continue at line %s."
)
_ACTION_MSG_5 = _(
    "Changes were detected at lines: %s; the player will jump "
    "forward from line %s."
)


def _show_modified_lines_and_action(tmp_data: _TmpData) -> List[str]:
    changes = _get_modified_lines_representation(tmp_data.modified_lines)
    delta = 1
    msg = _ACTION_MSG_1
    jump_to = tmp_data.jump_to
    state = tmp_data.baseline.state
    if jump_to is not None:
        if tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
            pass
        elif jump_to < state.pointer:
            msg = _ACTION_MSG_2
        elif jump_to == state.pointer:
            msg = _ACTION_MSG_3
        elif state.eol and jump_to == state.pointer + 1:
            msg = _ACTION_MSG_4
            delta = 2
        elif jump_to >= state.pointer:
            msg = _ACTION_MSG_5
    return [msg % (changes, state.pointer + delta)]


def _get_modified_lines_representation(modified_lines: List[int]) -> str:
    # Create a list of contiguous ranges:
    # [(start1, end1), (start2, end2), ...]
    first = modified_lines[0]
    tmp = [(first, first)]
    last = first
    for line in modified_lines[1:]:
        if line == last + 1:
            tmp[-1] = (first, line)
        else:
            first = line
            tmp.append((first, first))
        last = line
    # Add 1 to line numbers for printing:
    tmp = [(x[0] + 1, x[1] + 1) for x in tmp]
    # Stringify ranges:
    tmp2: List[str] = [str(x[0]) if x[0] == x[1] else "%s-%s" % x for x in tmp]
    return ", ".join(tmp2)


def _get_jump_and_action(tmp_data: _TmpData) -> Tuple[Optional[int], Action]:
    jump = _jump_modified_lines(tmp_data)
    if jump is not None:
        return jump, _get_default_action(tmp_data)
    elif len(tmp_data.lines) <= tmp_data.baseline.state.pointer:
        return _jump_end_of_file(tmp_data)
    elif tmp_data.baseline.restart_on_touch:
        return _jump_restart_on_touch(tmp_data), RESTART
    else:
        return None, NO_ACTION


def _jump_modified_lines(tmp_data: _TmpData) -> Optional[int]:
    modified_lines = tmp_data.modified_lines
    if (
        not modified_lines
        or tmp_data.baseline.tracking_mode == NO_TRACKING
    ):
        return None
    elif tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
        return 0
    elif tmp_data.baseline.tracking_mode == FORWARD_TRACKING:
        if (
            tmp_data.baseline.sequence_mode is SequenceModified
            and tmp_data.baseline.player_was_running_and_not_paused
            and modified_lines[0] > tmp_data.baseline.state.pointer
        ):
            return None
        else:
            return modified_lines[0]
    else:  # BACKWARD_TRACKING
        state = tmp_data.baseline.state
        line_number = state.pointer + (1 if state.eol else 0)
        if modified_lines[0] <= line_number:
            return modified_lines[0]
        else:
            return None


def _jump_end_of_file(tmp_data: _TmpData) -> Tuple[Optional[int], Action]:
    if tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
        return 0, _get_default_action(tmp_data)
    else:
        return len(tmp_data.lines)-1, STOP


def _jump_restart_on_touch(tmp_data: _TmpData) -> Optional[int]:
    if tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
        return 0
    else:
        return None


def _get_default_action(tmp_data):
    if (
        tmp_data.baseline.player_was_running_and_not_paused
        or tmp_data.baseline.restart_after_change
        or tmp_data.baseline.restart_on_touch
    ):
        return RESTART
    else:
        return NO_ACTION


def _get_basic_spoken_feedback(tmp_data: _TmpData) -> List[str]:
    if tmp_data.baseline.feedback_mode == NO_FEEDBACK:
        return []
    spoken_feedback = []
    if tmp_data.changed_again:
        spoken_feedback.extend(_get_message(tmp_data, "file-changed-again"))
    if len(tmp_data.lines) == 0:
        spoken_feedback.extend(_get_message(tmp_data, "file-is-empty"))
        return spoken_feedback
    if tmp_data.blank_areas_changed:
        spoken_feedback.extend(_get_message(tmp_data, "blank-areas-changed"))
    spoken_feedback.extend(_feedback_for_length_change(tmp_data))
    if not tmp_data.modified_lines:
        spoken_feedback.extend(_feedback_when_no_modified_lines(tmp_data))
    else:
        spoken_feedback.extend(_feedback_when_modified_lines(tmp_data))
    return spoken_feedback


def _feedback_for_length_change(tmp_data: _TmpData) -> List[str]:
    messages = []
    newlen = len(tmp_data.lines)
    oldlen = len(tmp_data.baseline.state.lines)
    if newlen < oldlen:
        messages.extend(_get_message(tmp_data, "file-decreased"))
        if newlen <= tmp_data.baseline.state.pointer:
            return _get_message(tmp_data, "file-too-short")
    elif newlen > oldlen:
        messages.extend(_get_message(tmp_data, "file-increased"))
    return messages


def _feedback_when_no_modified_lines(tmp_data: _TmpData) -> List[str]:
    newlen = len(tmp_data.lines)
    oldlen = len(tmp_data.baseline.state.lines)
    if newlen == oldlen:
        if not tmp_data.changed_again:
            return _get_message(tmp_data, "no-changes")
        else:
            return _get_message(tmp_data, "changes-reverted")
    else:
        return []


def _feedback_when_modified_lines(tmp_data: _TmpData) -> List[str]:
    messages = []
    if tmp_data.modified_lines[0] < tmp_data.baseline.state.pointer:
        messages.extend(_get_message(tmp_data, "changes-before"))
    elif tmp_data.modified_lines[0] == tmp_data.baseline.state.pointer:
        messages.extend(_get_message(tmp_data, "changes-here"))
    elif (
        tmp_data.baseline.state.eol
        and tmp_data.modified_lines[0] == tmp_data.baseline.state.pointer + 1
    ):
        messages.extend(_get_message(tmp_data, "changes-next"))
    else:
        messages.extend(_get_message(tmp_data, "changes-after"))
    if len(tmp_data.modified_lines) > 1:
        messages.extend(_get_message(tmp_data, "many-changes"))
    return messages


def _feedback_for_action_taken(tmp_data: _TmpData) -> List[str]:
    if tmp_data.baseline.feedback_mode == NO_FEEDBACK:
        return []
    elif tmp_data.action == RESTART:
        return _feedback_for_restart(tmp_data)
    elif tmp_data.jump_to is not None:
        return _feedback_for_jump(tmp_data)
    else:
        return []


def _feedback_for_restart(tmp_data: _TmpData) -> List[str]:
    assert tmp_data.action == RESTART
    pointer = tmp_data.baseline.state.pointer
    if tmp_data.baseline.tracking_mode == RESTART_FROM_BEGINNING:
        return _get_message(tmp_data, "starting-again")
    elif (
        tmp_data.baseline.sequence_mode is SequenceModified
        and not tmp_data.baseline.state.said_anything
    ):
        return []
    elif (
        not tmp_data.baseline.player_was_running_and_not_paused
        and not tmp_data.baseline.restarting_message_when_not_playing
    ):
        return []
    elif tmp_data.jump_to is None or tmp_data.jump_to == pointer:
        return _get_message(tmp_data, "restarting")
    elif tmp_data.jump_to < pointer:
        return _get_message(tmp_data, "jumping-back")
    elif tmp_data.jump_to > pointer:
        if tmp_data.baseline.state.eol and tmp_data.jump_to == pointer + 1:
            return _get_message(tmp_data, "continuing")
        else:
            return _get_message(tmp_data, "jumping-forward")
    else:
        return []


def _feedback_for_jump(tmp_data: _TmpData) -> List[str]:
    jump_to = tmp_data.jump_to
    assert jump_to is not None
    assert tmp_data.action != RESTART
    pointer = tmp_data.baseline.state.pointer
    if jump_to < pointer:
        if tmp_data.modified_lines and jump_to == tmp_data.modified_lines[0]:
            return _get_message(tmp_data, "jumping-back")
        elif len(tmp_data.lines) <= pointer:
            return _get_message(tmp_data, "file-too-short", True)
        else:
            return []
    elif jump_to == pointer:
        return _get_message(tmp_data, "changes-here", True)
    else:
        return _get_message(tmp_data, "jumping-forward")


def _get_message(
    tmp_data: _TmpData, key: str, mandatory: bool = False
) -> List[str]:
    if key in tmp_data.spoken_feedback:
        return []
    else:
        feedback_mode = (
            FULL_FEEDBACK if mandatory else tmp_data.baseline.feedback_mode
        )
        return get_message(
            tmp_data.baseline.feedback_messages, feedback_mode, key
        )


def get_message(
    feedback_messages: Dict[str, str], feedback_mode: _FeedbackMode, key: str
) -> List[str]:
    if key in feedback_messages and message_levels[key] <= feedback_mode:
        return [feedback_messages[key]]
    return []
