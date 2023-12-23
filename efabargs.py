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


__version__ = "2.0-beta"


###############################################################################
# Import global packages and initialize global CONSTANTS
from efabglobals import *

import efabseq
import efabtracking


_SECURITY_WARNING = _("SECURITY WARNING: read the manual before using "
                      "this option!")
_OPTIONS_WARNING = _("NOTE: read the manual and use with caution")


FORCE_EXEC_SHORT = "-f"

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
FORCE_EXEC_LONG = "--force-execution"


_args = None


def get_args():
    return _args or _get_args()


def _get_args():
    global _args

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
        % _SECURITY_WARNING,
    )
    parser.add_argument(
        "-v", "--voice", metavar=_("<name of the voice to be used>")
    )
    parser.add_argument(
        "-p",
        PAUSE_BEFORE_SWITCH,
        nargs="?",
        const=3,
        default=0,
        type=int,
        metavar=_("<pause length in seconds>"),
    )
    parser.add_argument(
        "-P",
        PAUSE_BETWEEN_SWITCH,
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
        "-t", "--tracking-mode",
        choices=efabtracking.tracking_modes_dict().keys(),
        default=efabtracking.default_tracking_mode_key()
    )
    group.add_argument(
        "--sequence-mode",
        choices=efabseq.sequence_modes_dict().keys(),
        default=efabseq.default_sequence_mode_key()
    )

    parser.add_argument(
        "-F", "--feedback-mode",
        choices=efabtracking.feedback_modes_dict().keys(),
        default=efabtracking.default_feedback_mode_key()
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
        FORCE_EXEC_SHORT, FORCE_EXEC_LONG, action="store_true", default=False
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
            % _SECURITY_WARNING
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
        LEFT_INDENT_SWITCH,
        nargs="?",
        default=0,
        type=int,
        metavar=_("<how many spaces>"),
    )
    parser.add_argument(
        RIGHT_INDENT_SWITCH,
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
        KEY_BINDINGS_SWITCH,
        default=None,
        metavar=_("<configuration file for converting keystrokes to "
                  "commands>"),
    )
    group1.add_argument(
        ADD_KEY_BINDINGS_SWITCH,
        default=None,
        metavar=_(
            "<additive configuration file for converting keystrokes to "
            "commands>"
        ),
    )
    group1.add_argument(
        SCRIPTED_MODE_SWITCH, action="store_true", default=False
    )
    parser.add_argument(
        "--opt",
        default="",
        metavar=_("<options that will be passed to espeak> %s")
        % _OPTIONS_WARNING,
        help=_("This option must use the following syntax: %s")
        % "--opt='-opt1 -opt2 ...'",
    )
    group2 = parser.add_mutually_exclusive_group(required=True)
    group2.add_argument(
        "-K",
        SAVE_KEY_BINDINGS_SWITCH,
        nargs="?",
        const="-",
        default=None,
        metavar=_(
            "<file where the default configuration for keystrokes will be "
            "saved>"
        ),
    )
    group2.add_argument(
        EDIT_KEY_BINDINGS_SWITCH,
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
        ) % _SECURITY_WARNING,
    )
    group2.add_argument("file", nargs="?", metavar=_("<file to be read>"))
    _args = parser.parse_args()
    return _args
