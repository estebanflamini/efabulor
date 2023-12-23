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

import efabseq
import efablogger
import efabtracking
import efabuserinput


_true_values = ["true", "1"]
_false_values = ["false", "0"]
_boolean_values = _true_values + _false_values


READONLY_MSG = (
    "Internal error in RuntimeOptions: trying to modify readonly "
    "option %s."
)


def _check_name(name):
    if not re.match(r"[a-z][a-z_]*[a-z]$", name):
        raise AttributeError(
            "Internal error in RuntimeOptions: invalid option name %s."
            % name
        )


_lock = threading.RLock()


class _Option:

    def __init__(self, prompt=None, readonly=False):
        self._prompt = prompt or _("Modifying option.")
        self._readonly = readonly
        self._msg = repr

    def __set_name__(self, owner, name):
        _check_name(name)
        owner.valid_names.append(name)
        self._public_name = name
        self._private_name = "_" + name

    def __get__(self, obj, objtype=None):
        with _lock:
            return getattr(obj, self._private_name)

    def __set__(self, obj, value):
        if self._readonly:
            raise AttributeError(
                READONLY_MSG % self._public_name
            )
        with _lock:
            setattr(obj, self._private_name, value)

    def log(self, value, mandatory=False):
        with _lock:
            efablogger.say(
                self._msg(value),
                type_of_msg=efablogger.INFO,
                mandatory=mandatory
            )


class _BooleanOption(_Option):

    def __init__(self, msg_true, msg_false, **kwargs):
        super().__init__(**kwargs)
        self._msg = lambda x: msg_true if x else msg_false

    @staticmethod
    def _validate(value):
        return value in _boolean_values


class _IntervalOption(_Option):

    def __init__(self, msg, valid_values=None, **kwargs):
        super().__init__(**kwargs)
        self._msg = msg
        self._valid_values = valid_values

    def _validate(self, value):
        return (
            value.isdigit() and (
                self._valid_values is None
                or self._valid_values[0] <= int(value) <= self._valid_values[1]
            )
        )


class _StringOption(_Option):

    def __init__(self, msg, valid_values=None, **kwargs):
        super().__init__(**kwargs)
        self._msg = msg
        self._valid_values = valid_values

    def _validate(self, value):
        return self._valid_values is None or value in self._valid_values


class _MappingOption(_Option):

    def __init__(self, msg, mapping, **kwargs):
        super().__init__(**kwargs)
        self._msg = msg
        self._mapping = mapping

    def _validate(self, value):
        return value in self._mapping.keys()

    def log(self, value, mandatory=False):
        value = {v: k for k, v in self._mapping.items()}[value]
        super().log(value, mandatory)


class RuntimeOptions:

    valid_names = []

    input_encoding = _StringOption(
        lambda x: _("Encoding used for input: %s") % x, readonly=True
    )

    config_encoding = _StringOption(None, None, readonly=True)

    lang = _StringOption(
        lambda x: _("Language used for reading: %s") % x, readonly=True
    )

    voice = _StringOption(
        lambda x: _("Voice used for reading: %s") % x, readonly=True
    )

    speed = _IntervalOption(
        lambda x: _("Reading speed: %s words/minute") % x,
        (MINSPEED, MAXSPEED)
    )

    espeak_options = _StringOption(
        lambda x: _("Options for espeak set to: %s") % x, readonly=True
    )

    monitoring_interval = _IntervalOption(
        lambda x: _("Interval for checking file modification set to: %s") % x,
        (1, 3600)
    )

    no_showline = _BooleanOption(
        _("The current line will not be printed even if requested by the "
          "user."),
        _("The current line will be printed when requested by the user."),
    )

    no_echo = _BooleanOption(
        _("The current line will not be printed when the line number "
          "changes."),
        _("The current line will be printed when the line number changes."),
    )

    no_info = _BooleanOption(
        _("Informative messages will not be printed."),
        _("Informative messages will be printed."),
    )

    no_update_player = _BooleanOption(
        _("The player will not be restarted if the line number changes while "
          "reading."),
        _("The player will be restarted if the line number changes while "
          "reading."),
    )

    show_line_number = _BooleanOption(
        _("Line numbers will be printed."),
        _("Line numbers will not be printed."),
    )

    show_total_lines = _BooleanOption(
        _("Number of total lines will be printed."),
        _("Number of total lines will not be printed."),
    )

    stop_after_current_line = _BooleanOption(
        _("The player will stop at the end of the current line."),
        _("The player will not stop at the end of the current line."),
    )

    reset_scheduled_stop_after_moving = _BooleanOption(
        _("A scheduled stop will not be reset after moving the line pointer."),
        _("A scheduled stop will be reset after moving the line pointer."),
    )

    stop_after_each_line = _BooleanOption(
        _("The player will stop after reading each line."),
        _("The player will not stop after reading each line."),
    )

    restart_after_change = _BooleanOption(
        _("The player will restart when changes to input files are detected."),
        _("The player will not restart when changes to input files are "
          "detected."),
    )

    restart_after_substitution_change = _BooleanOption(
        _("The player will restart when changes to the substituted line are "
          "detected."),
        _(
            "The player will not restart when changes to the substituted line "
            "are detected."
        ),
    )

    restart_on_touch = _BooleanOption(
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
        _("The program will exit when the end of the text is reached."),
        _("The program will not exit when the end of the text is reached."),
    )

    quit_without_prompt = _BooleanOption(
        _("The program will not ask for confirmation when asked to quit."),
        _("The program will ask for confirmation when asked to quit."),
    )

    pause_before = _IntervalOption(
        lambda x: _(
            "The reader will pause %s second(s) before starting to read when "
            "stopped."
        ) % x,
    )

    pause_between = _IntervalOption(
        lambda x: _("The reader will pause %s second(s) between lines.") % x
    )

    left_indent = _IntervalOption(
        lambda x: _("A left indent of %s space(s) will be used.") % x
    )

    right_indent = _IntervalOption(
        lambda x: _("A right indent of %s space(s) will be used.") % x
    )

    window_width_adjustment = _IntervalOption(
        lambda x: _("%s space(s) will be added to the right indent.") % x
    )

    sequence_mode = _MappingOption(
        lambda x: _("Sequence mode set to: %s.") % x,
        efabseq.sequence_modes_dict(),
        prompt=_("Choose a sequence mode:"),
    )

    tracking_mode = _MappingOption(
        lambda x: _("Tracking mode set to: %s.") % x,
        efabtracking.tracking_modes_dict(),
        prompt=_("Choose a tracking mode:"),
    )

    feedback_mode = _MappingOption(
        lambda x: _("Feedback mode set to: %s.") % x,
        efabtracking.feedback_modes_dict(),
        prompt=_("Choose a feedback mode:"),
    )

    apply_subst = _BooleanOption(
        _("Substitution rules will be applied."),
        _("Substitution rules will not be applied."),
    )

    show_subst = _BooleanOption(
        _(
            "The effect of substitution rules will be shown instead of the "
            "actual text."
        ),
        _(
            "The effect of substitution rules will not be shown instead of "
            "the actual text."
        ),
    )

    @classmethod
    def valid_name(cls, name):
        return name.replace("-", "_") in cls.valid_names

    @classmethod
    def valid_option(cls, name, value):
        return cls.__dict__[name.replace("-", "_")]._validate(value)

    def set_valid_values(self, name, values):
        public_name, private_name = self._get_names(name)
        self.__class__.__dict__[public_name]._valid_values = values

    def log(self, name, mandatory=False):
        public_name, private_name = self._get_names(name)
        option = self.__class__.__dict__[public_name]
        value = self.__dict__[private_name]
        option.log(value, mandatory)

    def _get_names(self, name):
        # Exceptions will be caught by efabcmd.process()
        public_name = name.replace("-", "_")
        private_name = "_" + public_name
        if private_name not in self.__dict__:
            raise AttributeError(_("Wrong option name"))
        return public_name, private_name

    def getopt(self, name):
        public_name, private_name = self._get_names(name)
        return getattr(self, public_name)

    def modify(self, name, *args):
        # Exceptions will be caught by efabcmd.process()
        public_name, private_name = self._get_names(name)
        if len(args) > 1:
            raise AttributeError(_("Too many arguments (must be zero or one)"))
        else:
            descriptor = self.__class__.__dict__[public_name]
            if descriptor._readonly:
                raise AttributeError(READONLY_MSG % public_name)
            old_value = self.getopt(public_name)
            if len(args) == 0:
                value = self._modify(
                    descriptor, public_name, self.__dict__[private_name]
                )
            else:
                value = args[0]
                if not descriptor._validate(value):
                    raise AttributeError(
                        _("Invalid value %s for option %s") % (value, name)
                    )
                value = self._translate(descriptor, value)
            if value is not None:
                setattr(self, public_name, value)
                self._adjust_modes(public_name)
            return old_value != self.getopt(public_name)

    def _modify(self, descriptor, public_name, current_value):
        if isinstance(descriptor, _BooleanOption):
            return not current_value
        else:
            if isinstance(descriptor, _MappingOption):
                inv_mapping = {v: k for k, v in descriptor._mapping.items()}
                current_value = inv_mapping[current_value]
                new_mode = efabuserinput.choose_mode(
                    descriptor._prompt, descriptor._mapping, current_value
                )
                if new_mode is not None:
                    return self._translate(descriptor, new_mode)
            else:
                efablogger.say(
                    _("Enter a value for option %s. Press <Enter> to cancel.")
                    % public_name.replace("_", "-"),
                    efablogger.INTERACTION
                )
                return self._translate(
                    descriptor, self._enter_value(descriptor)
                )
        return None

    def _enter_value(self, descriptor):
        while True:
            value = efabuserinput.getline()
            efablogger.separate(efablogger.INTERACTION)
            if not value.strip():
                efablogger.report_action_cancelled()
                return None
            elif not descriptor._validate(value):
                efablogger.say(
                    _(
                        "The entered value is not valid. Try again or press "
                        "<Enter>."
                    ),
                    efablogger.INTERACTION
                )
            else:
                return value

    def _translate(self, descriptor, value):
        if value is None:
            return None
        elif isinstance(descriptor, _BooleanOption):
            return value in _true_values
        elif isinstance(descriptor, _IntervalOption):
            return int(value)
        elif isinstance(descriptor, _MappingOption):
            return descriptor._mapping[value]
        elif isinstance(descriptor, _StringOption):
            return value
        else:
            raise AttributeError(
                _("Trying to set value to an option of unknown type")
            )

    def _adjust_modes(self, public_name):
        if (
            public_name == "tracking_mode"
            and self._sequence_mode is not efabseq.SequenceNormal
        ):
            self.sequence_mode = efabseq.SequenceNormal
            self.log("sequence-mode")
        elif (
            public_name == "sequence_mode"
            and self.sequence_mode in [
                efabseq.SequenceModified, efabseq.SequenceRandom
            ]
            and self.tracking_mode != efabtracking.FORWARD_TRACKING
        ):
            self.tracking_mode = efabtracking.FORWARD_TRACKING
            self.log("tracking-mode")

    def __init__(self, args):
        self.valid_names = []
        # Use private names to set readonly options.
        # TODO: in a future version, we might make all options writable.
        self._input_encoding = _get_encoding_aux(args.encoding)
        self._config_encoding = _get_encoding_aux(args.config_encoding)
        self._espeak_options = args.opt
        self._lang = None  # To be set during program's setup
        self._voice = None  # To be set during program's setup

        # Can use public names for writable options.
        self.speed = args.speed
        self.no_showline = args.no_showline
        self.no_echo = args.no_echo
        self.no_info = args.no_info
        self.no_update_player = args.no_update_player
        self.show_line_number = args.show_line_number
        self.show_total_lines = args.show_total_lines
        self.reset_scheduled_stop_after_moving = \
            not args.no_reset_scheduled_stop_after_moving
        self.stop_after_each_line = args.stop_after_each_line
        self.restart_after_change = not args.no_restart_after_change
        self.restart_after_substitution_change = \
            args.restart_after_substitution_change
        self.restart_on_touch = args.restart_on_touch
        self.restarting_message_when_not_playing = \
            not args.no_restarting_message_when_not_playing
        self.reload_when_not_playing = not args.no_reload_when_stopped
        self.close_at_end = args.close_at_end
        self.quit_without_prompt = args.quit_without_prompt
        self.pause_before = args.pause_before
        self.pause_between = args.pause_between
        self.left_indent = args.left_indent
        self.right_indent = args.right_indent
        self.window_width_adjustment = args.window_width_adjustment

        self.stop_after_current_line = False

        self.sequence_mode = efabseq.sequence_mode(args.sequence_mode)
        self.tracking_mode = (
            efabtracking.tracking_mode(args.tracking_mode)
            if self.sequence_mode == efabseq.SequenceNormal
            else efabtracking.FORWARD_TRACKING
        )
        self.feedback_mode = efabtracking.feedback_mode(args.feedback_mode)

        self.apply_subst = not args.raw
        self.show_subst = args.show_subst

        self.monitoring_interval = args.monitoring_interval

    def set_lang(self, lang):
        # Use private name to set readonly option
        self._lang = lang
        self.log("lang")

    def set_voice(self, voice):
        # Use private name to set readonly option
        self._voice = voice
        self.log("voice")


def _get_encoding_aux(encoding):
    if encoding:
        try:
            codecs.encode("", encoding)
            return encoding
        except Exception as e:
            sys.exit(str(e))
    else:
        return SYSTEM_ENCODING
