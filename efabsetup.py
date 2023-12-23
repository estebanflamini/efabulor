#!/usr/bin/env python3

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
import efabargs
import efabregex
import efabloader
import efablogger
import efabtracking
import efabuserinput
from efabplayer import Player
from efabrto import RuntimeOptions
from efabmonitor import FileMonitor
from efabsubst import Substitutions
from efabcore import terminate, start_daemon


_WILL_CONTINUE = _(
    "The player will stop now. If you restart the player, the program will "
    "continue as if the text was not modified."
)

_WRONG_OPTION_COMBINATION_MSG = _("%s and %s cannot be used at the same time.")
_WRONG_INT = _(
    "The %s option must be an integer greater than or equal to zero."
)
_MONITOR_INTERVAL_ERROR = _(
    "The monitoring interval must be an integer greater than zero."
)
_SPEED_ERROR = _("The speed cannot be less than %s nor greater than %s.")
_INVALID_FLAGS = _("Invalid flags for regular expressions: %s.")

_ERROR_SAVING_BINDINGS = _(
    "An error has occurred while trying to save keystroke configuration to "
    "file: %s"
)
_OVERWRITE_FILE = _("File %s already exists. Overwrite it?")
_INVALID_FILE_NAME = _("%s is not a valid file name.")
_BINDINGS_SAVED_TO = _(
    "Default keystroke configuration was saved to file: %s\n"
)
_FILE_EXISTS = _("File %s already exists. Choose an option:")
_APPEND = _("Append the key bindings at the end.")
_OVERWRITE = _("Overwrite the current file.")
_CONFIRM = _("Are you sure?")
_CANCELLED = _("The action was cancelled.")

_ENTER_ACTION = _("Enter an action name, or press <Enter> to end.")
_WRONG_ACTION = _("The command '%s' is not well formed.")
_SELECT_KEY = _("Press the key you want to associate with the action.")
_KEY_ASSOCIATED = _("Keystroke %s will be associated with action: %s")

_CONFIRM_SAVING = _(
    "Please confirm that you want to save the key bindings to file %s."
)

_UNABLE_TO_CHECK_RUNNING_INSTANCE = _(
    "The program could not check for a running instance."
)
_ASSUME_NO_INSTANCE = _("The program will assume no instance is running.")
_ALREADY_RUNNING = _(
    "An instance seems to be running as one of the following processes:"
)
_HOW_TO_FORCE_EXECUTION = _(
    "Use the %s option to force program execution."
) % efabargs.FORCE_EXEC_SHORT


_BINDING_PATTERN = r"^(\S+)\s+(.+)$"

_BINDING_DESCRIPTION = _(
    "The following line is wrong: '%s'. Key bindings must consist of a key "
    "specification, followed by one or more spaces, followed by the desired "
    "action."
)
_REPEATED_BINDING = _(
    "The following keystroke appears more than once in the configuration "
    "file: %s"
)
_BINDING_REDEFINED = _("The binding for key %s has been redefined to be '%s'.")
_NO_BINDING_FOR_QUIT = _(
    "A keystroke must be configured for the '%s' or '%s' action."
)
_ERROR_IN_BINDING_FILE = _("Error in keystroke configuration file: %s.")

_NON_OPTIONS_FOR_ESPEAK = _("Non-options passed as options for espeak: %s")
_WRONG_ESPEAK_OPTIONS = _("Wrong options for espeak were given: %s.")

_ERROR_QUERYING_LANGUAGES = _(
    "An error has occurred while trying to query espeak’s available languages."
)
_UNABLE_TO_VALIDATE_LANGUAGE = _(
    "The program cannot determine if the given language is valid."
)
_WILL_USE_LANG_ANYWAY = _(
    "The program will try to use the given language (%s) anyway."
)
_INVALID_LANGUAGE = _(
    "The language given (%s) is not configured for espeak. Accepted languages "
    "are:\n\n%s."
)
_LANG_CONFIG_FILE = _("Language configuration file: %s")

_ERROR_READING_FILE = _("There was an error trying to read from file: %s")
_NO_LANG_CONFIG = _("No language configuration file was provided.")
_WRONG_LANG_CONFIG_LINE = _("Wrong line:\n\n%s\n\nin file: %s.")

_UNABLE_TO_GET_VOICE = _(
    "The voice for reading could not be determined, the program will try to "
    "use espeak’s default voice."
)
_NO_VOICES_FOR_LANG = _("No voices for language %s were found.")
_ERROR_QUERYING_VOICES = _(
    "An error has occurred while trying to query espeak’s available voices."
)
_TESTING_VOICE = _("Testing voice: %s")
_ERROR_TESTING_VOICE = _(
    "An error has occurred while testing espeak with voice %s."
)


# A dataclass to pass all dependencies to efabcmd within a single object
@dataclass
class Core:
    source: efabloader.InputSource
    loader: Callable[
        [
            efabloader.InputSource,
            RuntimeOptions,
            Callable[[str, List[str]], None],
            Callable[[Exception], None]
        ], None
    ]
    player: Player
    options: RuntimeOptions
    substitutions: Substitutions
    transformations: List[str]
    monitor: FileMonitor
    monitored: List[str]
    clmonitored: List[str]


def setup(main_file):

    args = efabargs.get_args()
    options = RuntimeOptions(args)
    efablogger.register_options(options)

    _configure_signal_handlers()

    _check_wrong_argument_combinations(args)
    _check_wrong_arguments(args)
    _check_valid_files(args)

    _set_default_flags(args)

    if args.save_default_key_bindings:
        _save_default_key_bindings(args, options)
    elif args.edit_key_bindings:
        _edit_key_bindings(args, options)

    _check_running_instance(args, main_file)

    _set_key_bindings(args, options)

    _check_espeak_options(options.espeak_options)

    lang, valid_languages = _get_language(args)
    options.set_lang(lang)

    if valid_languages is not None:
        options.set_valid_values("lang", valid_languages)

    voice, available_voices, feedback_messages = _get_language_options(
        args, options
    )

    if voice is not None:
        options.set_voice(voice)

    if available_voices is not None:
        options.set_valid_values("voice", available_voices)

    options.log("input_encoding")

    source = efabloader.get_source(args, options)

    substitution_rule_files = args.substitution_rules
    substitutions = _get_substitution_rules(substitution_rule_files, options)
    substitutions.load()

    player = Player(options, substitutions, feedback_messages)

    def text_loading_error(e, player):
        text_loaded = player.text_is_loaded()
        with efablogger.lock:
            efablogger.say(
                "An error has occurred while trying to read the text source.",
                type_of_msg=efablogger.ERROR
            )
            efablogger.report_error(e)
            if text_loaded:
                efablogger.say(_WILL_CONTINUE, type_of_msg=efablogger.INFO)
        if text_loaded:
            player.stop()
        else:
            terminate(PROGRAM_MUST_TERMINATE_NOW)

    def loader():
        efabloader.load_text(
            source,
            options,
            on_success=lambda text, lines: player.set_text(text, lines),
            on_error=lambda e: text_loading_error(e, player)
        )

    start_daemon(loader)

    monitored = []

    if args.file is not None:
        monitored.append(args.file)

    clmonitored = _get_monitored_input_files(args)
    monitored.extend(clmonitored)
    monitored.extend(args.transformation_rules)

    monitor = FileMonitor(options)

    def input_file_changed(name_of_changed_file):
        if player.running() or options.reload_when_not_playing:
            start_daemon(loader)
        else:
            player.schedule_delayed_reload(loader)

    monitor.register(
        group=monitored,
        action=input_file_changed
    )

    def substitution_file_changed(name_of_changed_file):
        substitutions.reload()
        player.substitution_rules_changed()

    monitor.register(
        group=substitution_rule_files,
        action=substitution_file_changed,
    )

    start_daemon(monitor.run)

    return Core(
        source, loader, player, options, substitutions,
        args.transformation_rules, monitor, monitored, clmonitored
    )


def _configure_signal_handlers():
    signal.signal(
        signal.SIGTERM,
        lambda signum, frame: terminate(
            TERMINATED_BY_SIGNAL % "SIGTERM"
        ),
    )
    if LINUX:
        signal.signal(
            signal.SIGHUP,
            lambda signum, frame: terminate(
                TERMINATED_BY_SIGNAL % "SIGHUP"
            ),
        )


def _check_wrong_argument_combinations(args):
    if args.scripted and args.save_default_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (
                efabargs.SCRIPTED_MODE_SWITCH,
                efabargs.SAVE_KEY_BINDINGS_SWITCH
            )
        )
    if args.scripted and args.edit_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (
                efabargs.SCRIPTED_MODE_SWITCH,
                efabargs.EDIT_KEY_BINDINGS_SWITCH
            )
        )
    if args.key_bindings and args.save_default_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (efabargs.KEY_BINDINGS_SWITCH, efabargs.SAVE_KEY_BINDINGS_SWITCH)
        )
    if args.add_key_bindings and args.save_default_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (
                efabargs.ADD_KEY_BINDINGS_SWITCH,
                efabargs.SAVE_KEY_BINDINGS_SWITCH
            )
        )
    if args.key_bindings and args.edit_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (
                efabargs.KEY_BINDINGS_SWITCH,
                efabargs.EDIT_KEY_BINDINGS_SWITCH
            )
        )
    if args.add_key_bindings and args.edit_key_bindings:
        terminate(
            _WRONG_OPTION_COMBINATION_MSG
            % (
                efabargs.ADD_KEY_BINDINGS_SWITCH,
                efabargs.EDIT_KEY_BINDINGS_SWITCH
            )
        )


def _check_wrong_arguments(args):
    if args.monitoring_interval <= 0:
        terminate(_MONITOR_INTERVAL_ERROR)
    if args.speed < MINSPEED or args.speed > MAXSPEED:
        terminate(_SPEED_ERROR % (MINSPEED, MAXSPEED))
    if args.pause_before < 0:
        terminate(_WRONG_INT % efabargs.PAUSE_BEFORE_SWITCH)
    if args.pause_between < 0:
        terminate(_WRONG_INT % efabargs.PAUSE_BETWEEN_SWITCH)
    if args.left_indent < 0:
        terminate(_WRONG_INT % efabargs.LEFT_INDENT_SWITCH)
    if args.right_indent < 0:
        terminate(_WRONG_INT % efabargs.RIGHT_INDENT_SWITCH)


def _set_default_flags(args):
    # We set default regex flags before calling any code which might depend on
    # them, and before performing setup steps which might be time consuming.
    flags = args.regex_flags.strip().replace(" ", "")
    if flags:
        try:
            efabregex.set_default_flags(flags)
        except efabregex.error:
            terminate(_INVALID_FLAGS % flags)


def _check_valid_files(args):
    if args.file is not None:
        efabloader.check_file_validity(args.file)
    if args.config_file:
        efabloader.check_file_validity(args.config_file)
    for fn in map(os.path.expanduser, args.transformation_rules):
        efabloader.check_file_validity(fn)
    for fn in map(os.path.expanduser, args.substitution_rules):
        efabloader.check_file_validity(fn)


def _save_default_key_bindings(args, options):
    output = None
    filename = args.save_default_key_bindings
    if filename == "-":
        output = sys.stdout
    elif os.path.exists(filename):
        if os.path.isfile(filename):
            if not efabuserinput.confirm_action(_OVERWRITE_FILE % filename):
                terminate(DEFAULT_ERROR_RETURNCODE)
        else:
            terminate(_INVALID_FILE_NAME % filename)
    try:
        if not output:
            output = open(
                filename, "w",
                encoding=options.config_encoding
            )
        for key, value in efabcmd.DEFAULT_BINDINGS.items():
            key = repr(key).strip("'")
            key = key.replace(" ", r"\x20")
            output.write("%s\t%s\n" % (key, value))
        if output is not sys.stdout:
            efablogger.say(
                _BINDINGS_SAVED_TO % filename, type_of_msg=efablogger.INFO,
            )
            output.close()
        terminate()
    except IOError as e:
        efablogger.say(
            _ERROR_SAVING_BINDINGS % filename, type_of_msg=efablogger.ERROR
        )
        terminate(REPORTED_ERROR_MSG % e)


def _edit_key_bindings(args, options):
    filename = args.edit_key_bindings
    do_append = False
    if filename != "-" and os.path.exists(filename):
        if os.path.isfile(filename):
            msg = _FILE_EXISTS % filename
            choices = [_APPEND, _OVERWRITE]
            action = efabuserinput.choose_mode(msg, choices, None)
            if action is None:
                terminate(DEFAULT_ERROR_RETURNCODE)
            elif action == _OVERWRITE:
                if not efabuserinput.confirm_action(_CONFIRM):
                    terminate(_CANCELLED)
            do_append = action == _APPEND
        else:
            terminate(_INVALID_FILE_NAME % filename)

    bindings = {}

    while True:
        efablogger.say(_ENTER_ACTION, type_of_msg=efablogger.INTERACTION)

        cmd = efabuserinput.getline()

        if not cmd:
            break

        efablogger.separate(efablogger.INTERACTION)

        cmd = cmd.strip()

        # In this version, only macros can be bound to keys
        if not efabcmd.is_macro(cmd):
            efablogger.say(
                efabcmd.MSG_INVALID_MACRO % cmd, type_of_msg=efablogger.ERROR
            )
            continue

        parsed_command = efabcmd.parse(cmd)
        if not parsed_command:
            efablogger.say(_WRONG_ACTION % cmd, type_of_msg=efablogger.ERROR)
            time.sleep(1)
            continue

        efablogger.say(_SELECT_KEY, type_of_msg=efablogger.INTERACTION)

        key = efabuserinput.getch()
        key = repr(key).strip("'")
        key = key.replace(" ", r"\x20")
        efablogger.say(
            _KEY_ASSOCIATED % (key, cmd), type_of_msg=efablogger.INTERACTION,
        )
        bindings[key] = cmd

    if bindings:
        try:
            if filename == "-":
                output = sys.stdout
            elif not efabuserinput.confirm_action(
                _CONFIRM_SAVING % filename
            ):
                terminate(DEFAULT_ERROR_RETURNCODE)
            else:
                output = False
            current_content = ""
            if do_append:
                with open(filename) as f:
                    current_content = f.read().strip() + "\n\n"
            output = output or open(
                filename,
                "w",
                encoding=options.config_encoding
            )
            output.write(current_content)
            for key, value in bindings.items():
                output.write("%s\t%s\n" % (key, value))
            if filename != "-":
                output.close()
        except Exception as e:
            efablogger.say(
                _ERROR_SAVING_BINDINGS % filename,
                type_of_msg=efablogger.ERROR,
            )
            efablogger.report_error(e)
            terminate(DEFAULT_ERROR_RETURNCODE)

    terminate()


def _check_running_instance(args, main_file):
    if args.force_execution:
        return
    this_instance = os.path.basename(main_file)
    procs = None
    if PSUTIL_INSTALLED:
        procs = psutil.process_iter(["pid", "name", "cmdline"])
        procs = [x for x in procs if x.info["cmdline"]]
        procs = [x for x in procs if x.info["name"].startswith("python")]
        procs = [x for x in procs if len(x.info["cmdline"]) > 1]
        procs = [x for x in procs if x.info["cmdline"][1] == this_instance]
        procs = [x for x in procs if x.pid != os.getpid()]
        procs = [str(x) for x in procs]
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
            procs = [
                x for x in procs
                if os.path.basename(x.split()[2]) == this_instance
            ]
            procs = [x for x in procs if x.split()[0] != str(os.getpid())]
        except Exception as e:
            efablogger.say(
                _UNABLE_TO_CHECK_RUNNING_INSTANCE,
                type_of_msg=efablogger.ERROR,
            )
            efablogger.report_error(e)
            efablogger.say(
                _ASSUME_NO_INSTANCE, type_of_msg=efablogger.INFO,
            )
            return
    if procs:
        efablogger.say(_ALREADY_RUNNING, type_of_msg=efablogger.ERROR)
        efablogger.say("\n".join(procs), type_of_msg=efablogger.ERROR_EXTENDED)
        efablogger.say(
            _HOW_TO_FORCE_EXECUTION, type_of_msg=efablogger.INFO,
        )
        terminate(DEFAULT_ERROR_RETURNCODE)


def _set_key_bindings(args, options):
    filename = (
        args.key_bindings
        or args.add_key_bindings
        or _get_default_key_bindings_file()
    )
    if not filename:
        key_bindings = efabcmd.DEFAULT_BINDINGS
    else:
        efabloader.check_file_validity(filename)
        _bindings = _read_config_file(
            filename, options.config_encoding
        )
        _bindings = _bindings.split("\n")
        # Be careful not to delete next line
        _bindings = list(map(str.strip, _bindings))
        _bindings = [x for x in _bindings if x]
        _bindings = [x for x in _bindings if not x.startswith("#")]
        _processed_bindings = []
        if args.add_key_bindings is not None:
            key_bindings = efabcmd.DEFAULT_BINDINGS
        else:
            key_bindings = {}
        for binding in _bindings:
            # binding was already stripped of spaces above
            m = re.match(_BINDING_PATTERN, binding)
            if not m:
                _report_key_binding_error(
                    _BINDING_DESCRIPTION % binding, filename,
                )
            key = translate_control_chars(m.group(1))
            value = m.group(2)
            if False and not efabcmd.is_macro(value):
                # In this version, we only allow macros in key conf. files
                _report_key_binding_error(
                    efabcmd.MSG_INVALID_MACRO % value,
                    filename,
                )
            if key in _processed_bindings:
                _report_key_binding_error(_REPEATED_BINDING % key, filename)
            else:
                _processed_bindings.append(key)
            if key in key_bindings:
                efablogger.say(
                    _BINDING_REDEFINED % (repr(key), value),
                    type_of_msg=efablogger.INFO,
                )
            key_bindings[key] = value
    binding_for_quit = False
    for key, binding in key_bindings.items():
        parsed_command = efabcmd.parse(binding)
        if not parsed_command:
            _report_key_binding_error(
                _WRONG_ACTION % binding, filename
            )
        elif efabcmd.contains_quit(parsed_command):
            binding_for_quit = True
    if not binding_for_quit:
        _report_key_binding_error(
            _NO_BINDING_FOR_QUIT % (
                efabcmd.MACRO_QUIT_ASK, efabcmd.MACRO_QUIT_NOW),
            filename,
        )
    efabcmd.set_bindings(key_bindings)


DEFAULT_KEY_BINDINGS_FILE = sys.path[0] + "/%s.key" % PROGNAME


def _get_default_key_bindings_file():
    if os.path.isfile(DEFAULT_KEY_BINDINGS_FILE):
        return DEFAULT_KEY_BINDINGS_FILE
    return None


def _report_key_binding_error(e, filename=None):
    if filename:
        efablogger.say(
            _ERROR_IN_BINDING_FILE % filename, type_of_msg=efablogger.ERROR,
        )
    else:
        efablogger.say("Internal error.", type_of_msg=efablogger.ERROR)
    terminate(REPORTED_ERROR_MSG % e)


def _read_config_file(fn, config_encoding):
    efabloader.check_file_validity(fn)
    with open(fn, "r", encoding=config_encoding) as f:
        return f.read()


# If you modify this method, be VERY careful to sanitize espeak_options
# (shlex.split or shlex.quote where appropriate), if you ever were to make the
# call through a shell.
def _check_espeak_options(espeak_options):
    if espeak_options:
        try:
            tmp_op = shlex.split(espeak_options)
            switch_before = False
            for token in tmp_op:
                if not token.startswith("-"):
                    if not switch_before:
                        terminate(_NON_OPTIONS_FOR_ESPEAK % token)
                    else:
                        switch_before = False
                else:
                    switch_before = True
            cmd = ["espeak"] + tmp_op + [" "]
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
        except Exception as e:
            terminate(_WRONG_ESPEAK_OPTIONS % espeak_options)


def _get_language(args):
    lang = args.lang or locale.getdefaultlocale()[0].split("_")[0]
    valid_languages, err = _get_valid_languages()
    if err:
        _report_error_checking_validity_of(lang, err)
        return lang, None
    else:
        if lang in valid_languages:
            return lang, valid_languages
        else:
            _report_invalid_language(lang, valid_languages)


def _get_valid_languages():
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
            raise EspeakError(cp.stderr.strip())
        tmp = cp.stdout.strip().split("\n")[1:]
        return [x.split()[1] for x in tmp],  None
    except Exception as e:
        return None, e


def _report_error_checking_validity_of(lang, e):
    efablogger.say(_ERROR_QUERYING_LANGUAGES, type_of_msg=efablogger.ERROR)
    efablogger.report_error(e)
    efablogger.say(_UNABLE_TO_VALIDATE_LANGUAGE, type_of_msg=efablogger.ERROR)
    efablogger.say(_WILL_USE_LANG_ANYWAY % lang, type_of_msg=efablogger.INFO)


def _report_invalid_language(lang, valid_languages):
    valid_languages = " ".join(valid_languages)
    valid_languages = textwrap.fill(
        valid_languages,
        efablogger.window_width(sys.stderr),
        break_on_hyphens=False,
    )
    terminate(_INVALID_LANGUAGE % (lang, valid_languages))


def _get_language_options(args, options):
    lang_config_file = _get_language_config_file(args, options.lang)
    if lang_config_file is not None:
        efablogger.say(
            _LANG_CONFIG_FILE % lang_config_file, type_of_msg=efablogger.INFO
        )
        try:
            preset_voice, feedback_messages = _load_language_config(
                lang_config_file, options.config_encoding
            )
        except ValueError as e:
            efablogger.report_error(e)
            terminate(DEFAULT_ERROR_RETURNCODE)
        except IOError as e:
            efablogger.say(
                _ERROR_READING_FILE % lang_config_file,
                type_of_msg=efablogger.ERROR,
            )
            terminate(REPORTED_ERROR_MSG % e)
    else:
        efablogger.say(_NO_LANG_CONFIG, type_of_msg=efablogger.INFO)
        preset_voice = None
        feedback_messages = {}

    voice, available_voices = _get_voice(
        args, options.lang, preset_voice
    )
    return voice, available_voices, feedback_messages


def _get_language_config_file(args, lang):
    if args.config_file:
        fns = [args.config_file]
    else:
        fns = [
            sys.path[0] + "/%s.%s.cfg" % (PROGNAME, lang),
            sys.path[0] + "/%s.cfg" % PROGNAME,
        ]
    for fn in fns:
        if os.path.isfile(fn):
            return fn
    return None


LOCALE_CONFIG_ELEMENT = r"^([a-z-]+):\s*(.+)$"


def _load_language_config(fn, config_encoding):
    conf = _read_config_file(fn, config_encoding).strip()
    conf = conf.split("\n")
    conf = list(map(str.strip, conf))
    conf = [x for x in conf if not x or x[0] != "#"]
    valid_keys = ["voice"] + list(efabtracking.feedback_message_keys())
    voice = None
    feedback_messages = {}
    for line in conf:
        line = line.strip()
        m = re.match(LOCALE_CONFIG_ELEMENT, line)
        if not m:
            raise ValueError(_WRONG_LANG_CONFIG_LINE % (line, fn))
        key = m.group(1)
        value = m.group(2)
        if key not in valid_keys:
            raise ValueError("Wrong option name '%s' in file %s." % (key, fn))
        elif key == "voice":
            voice = value
        else:
            feedback_messages[key] = value
    return voice, feedback_messages


def _get_voice(args, lang, preset_voice):
    voices = []
    if args.voice:
        voices.append(args.voice)
    if preset_voice:
        voices.append(preset_voice)
    available_voices = _get_available_voices(lang)
    voices.extend(available_voices)
    voice = None
    if voices:
        voice = _test_and_return_voice(voices)
    if voice:
        return voice, available_voices
    else:
        efablogger.say(_UNABLE_TO_GET_VOICE, type_of_msg=efablogger.INFO)
        return None, available_voices


def _get_available_voices(lang):
    try:
        # Sanitization of lang is not necessary unless you change the following
        # call to invoke a shell
        cp = subprocess.run(
            ["espeak", "--voices=%s" % lang],
            text=True,
            capture_output=True,
            check=True,
        )
        if cp.stderr:
            # espeak doesn't necessarily end with returncode != 0 in
            # certain cases
            raise Exception(cp.stderr.strip())
        query_output = cp.stdout.strip().split("\n")[1:]
        if query_output:
            return _get_preferred_voices(query_output)
        else:
            efablogger.say(
                _NO_VOICES_FOR_LANG % lang, type_of_msg=efablogger.ERROR
            )
    except Exception as e:
        efablogger.say(_ERROR_QUERYING_VOICES, type_of_msg=efablogger.ERROR)
        efablogger.report_error(e)
    return []


def _get_preferred_voices(query_output):
    voices = []
    tmp = [x for x in query_output if "mbrola" in x or "-mb-" in x]
    if tmp:
        voices.append(tmp[0].split()[3])
    tmp = [
        x for x in query_output if "mbrola" not in x and "-mb-" not in x
    ]
    if tmp:
        voices.append(tmp[0].split()[3])
    return voices


def _test_and_return_voice(voices):
    for v in voices:
        efablogger.say(_TESTING_VOICE % v, type_of_msg=efablogger.INFO)
        try:
            # Sanitization of v is not necessary unless you change the
            # following call to invoke a shell
            cp = subprocess.run(
                ["espeak", "-v", v, " "],
                text=True,
                capture_output=True,
                check=True,
            )
            if cp.stderr:
                # espeak doesn't necessarily end with returncode != 0
                # in certain cases
                raise EspeakError(cp.stderr.strip())
            else:
                return v
        except Exception as e:
            efablogger.say(
                _ERROR_TESTING_VOICE % v, type_of_msg=efablogger.ERROR
            )
            efablogger.report_error(e)
    return None


def _get_substitution_rules(files, options):
    substitution_rule_files = []
    for fn in files:
        efabloader.check_file_validity(fn)
        if fn not in substitution_rule_files:
            substitution_rule_files.append(fn)
    subst = Substitutions(substitution_rule_files, options)
    return subst


def _get_monitored_input_files(args):
    files = []
    for fn in args.monitored_file:
        efabloader.check_file_validity(fn, allow_dir=True)
        if fn not in files:
            files.append(fn)
    return files
