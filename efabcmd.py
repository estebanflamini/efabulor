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

import efabregex
import efablogger
import efabuserinput
from efabargs import get_args
from efabloader import InputSource
from efabrto import RuntimeOptions
from efabplayer import StoredSearch, Player, PlayerState
from efabcore import start_daemon, terminate, pause


if TYPE_CHECKING:
    _ = gettext.gettext


# This is the internal scripting language. It is an experimental feature.
# Beware that it might change or be removed in future versions without previous
# notice.


class _CoreProtocol(Protocol):
    state: PlayerState
    player: Player
    options: RuntimeOptions
    source: InputSource
    transformations: List[str]


_NulladicCommand = Callable[[_CoreProtocol], bool]
_DyadicCommand = Callable[[_CoreProtocol, Union[str, Iterable[str]]], bool]
_Command = Union[_NulladicCommand, _DyadicCommand]
_Binding = Dict[str, _Command]


# Commands which can only be executed once the text has been read.

_bindings_player: _Binding = {
    "showline": lambda core: core.player.showline(),
    "updateplayer": lambda core: core.player.update_player(),
    "resetpointer": lambda core: core.player.reset_pointer(),
    "refreshline": lambda core: core.player.refresh_line(),
    "toggle": lambda core: core.player.toggle(),
    "restart": lambda core: core.player.restart(),
    "stop": lambda core: core.player.stop(),
    "first": lambda core: core.player.first(),
    "last": lambda core: core.player.last(),
    "next": lambda core: core.player.next(),
    "previous": lambda core: core.player.previous(),
    "gorandom": lambda core: core.player.go_random(),
    "stoporprevious": lambda core: _stop_or_previous(core),
    "goline": lambda core, *x: _go(core, *map(int, x)),
    "find": lambda core, *x: _find(core, *x),
    "findnext": lambda core: core.player.find_next(),
    "findprev": lambda core: core.player.find_previous(),
    "goprevchange": lambda core: core.player.go_modified(False),
    "gonextchange": lambda core: core.player.go_modified(True),
    "lineno": lambda core: _cycle_line_number_printing(core),
    "logsubst": lambda core: core.substitutions.show_log(core.player),
    "logtransform": lambda core: _log_transformations(core),
}


# TODO: maybe replace *all* hardwired commands with constants like these
ASK_N_QUIT_CMD = "quit"
QUIT_CMD = "QUIT"

# Commands which can be executed before the text has been read.

_bindings_general: _Binding = {
    "sh": lambda core, *x: _run_in_shell(core, *x),
    "openshell": lambda core: _open_shell(core),
    "openfile": lambda core, x: _open_file(core, x),
    "openinputfile": lambda core: _open_input_file(core),
    "opensubst": lambda core: _choose_and_open_file(
        core,
        core.substitutions.rule_files(),
        _("No substitution rules were given.")
    ),
    "openclmonfile": lambda core: _choose_and_open_file(
        core,
        core.clmonitored,
        _("No command-line monitored files were given."),
    ),
    "opentransform": lambda core: _choose_and_open_file(
        core, core.transformations, _("No transformation rules were given."),
    ),
    "showinputcmd": lambda core: _show_input_command(core),
    "reload": lambda core: bool(start_daemon(core.loader)),
    "checkfiles": lambda core: core.monitor.check_files(say_it=True),
    "info": lambda core, *x: efablogger.say(" ".join(x), efablogger.INFO),
    "changespeed": lambda core, x: _change_speed(core, int(x)),
    "pause": lambda core, *x: pause(
        int(x[0]) if x else core.options.pause_before
    ),
    "modifyopt": lambda core, name, *x: _modify_option(core.options, name, *x),
    "getopt": lambda core, x: core.options.getopt(x),
    "cmd": lambda core: _command_loop(core),
    ASK_N_QUIT_CMD: lambda core: _quit(core, ask_for_confirmation=True),
    QUIT_CMD: lambda core: _quit(core, ask_for_confirmation=False),
}

# Operators

CMD_SEPARATOR_LOW = ";"
CMD_SEPARATOR_HIGH = "and"
CMD_SEPARATOR_THEN = "then"
CMD_SEPARATOR_ONMOVETHEN = "onmovethen"
CMD_PREFIX_NOECHO = "noecho"
CMD_PREFIX_NOINFO = "noinfo"
CMD_PREFIX_NOUPDATEPLAYER = "noupdateplayer"

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


############################################################################
# Implementation of some commands which are not implemented in other modules


def _stop_or_previous(core: _CoreProtocol) -> bool:
    if core.player.running_and_not_paused():
        core.player.stop()
        return False
    else:
        return core.player.previous()


def _go(core: _CoreProtocol, line_number: Optional[int] = None) -> bool:
    if line_number is not None:
        return core.player.go(line_number)
    else:
        core.player.stop()
        line_number = _get_line_number(core)
        if line_number is None:
            return False
        else:
            core.player.go(line_number)
            return True


def _get_line_number(core: _CoreProtocol) -> Optional[int]:
    with efablogger.lock:
        efablogger.say(_("Go to line:"), type_of_msg=efablogger.INTERACTION)
        line_number = efabuserinput.get_int()
        if line_number is None:
            return None
        elif line_number < 1 or line_number > core.player.last_line_number():
            efablogger.say(
                _("You must enter a line number between 1 and %s.")
                % core.player.last_line_number(),
                type_of_msg=efablogger.ERROR,
            )
            return None
        elif core.player.current_line_number() == line_number:
            efablogger.say(
                _("The player is already at line %s.") % line_number,
                type_of_msg=efablogger.INFO,
            )
            return None
        else:
            return line_number


SEARCH_PLAIN = "plain"
SEARCH_REGEX = "regex"
SEARCH_CI = "case-insensitive"
SEARCH_CS = "case-sensitive"

MSG_ENTER_PLAIN = _("Enter a search string (press Enter to cancel):")
MSG_ENTER_REGEX = _(
    "Enter a regular expression, without delimiters (press Enter to "
    "cancel):"
)

MSG_SEARCH_MODE = _("Search mode is: %s")
MSG_CASE_SENS = _("Case sensitivity is: %s")


def _find(
    core: _CoreProtocol,
    mode: Optional[str] = None,
    cs: Optional[str] = None,
    what: Optional[str] = None
) -> bool:

    with efablogger.lock:
        mode = mode or _choose_mode(core)
        if not mode:
            return False

        efablogger.say(MSG_SEARCH_MODE % mode, type_of_msg=efablogger.INFO)

        cs = cs or _choose_cs(core)
        if not cs:
            return False

        efablogger.say(MSG_CASE_SENS % cs, type_of_msg=efablogger.INFO)

        what = what or _enter_what(core.player, mode)
        if what:
            return _search(core.player, mode, cs, what)
        else:
            efablogger.report_action_cancelled()
            return False


def _choose_mode(core: _CoreProtocol) -> Optional[str]:
    core.player.stop()
    return efabuserinput.choose_mode(
        _("Choose a search mode:"),
        [SEARCH_PLAIN, SEARCH_REGEX],
        None,
    )


def _choose_cs(core: _CoreProtocol) -> Optional[str]:
    core.player.stop()
    return efabuserinput.choose_mode(
        _("Choose a case sensitivity mode:"),
        [SEARCH_CI, SEARCH_CS],
        None,
    )


def _enter_what(player: Player, mode: str) -> Optional[str]:
    player.stop()
    efablogger.say(
        MSG_ENTER_PLAIN if mode == SEARCH_PLAIN else MSG_ENTER_REGEX,
        type_of_msg=efablogger.INTERACTION,
    )
    what = efabuserinput.getline()
    efablogger.separate(efablogger.INTERACTION)
    return what


def _search(player: Player, mode: str, cs: str, what: str) -> bool:
    try:
        flags = efabregex.get_default_flags() & ~re.IGNORECASE
        flags |= re.IGNORECASE if cs == SEARCH_CI else 0
        if mode == SEARCH_PLAIN:
            regex = re.escape(what)
        else:
            regex = what
        pattern = re.compile(regex, flags=flags)
        return player.find(StoredSearch(what, pattern), 0)
    except re.error as e:
        with efablogger.lock:
            efablogger.report_error(e)
            efablogger.say(
                _("The search was cancelled because the pattern was wrong"),
                type_of_msg=efablogger.INFO,
            )
        return False


def _cycle_line_number_printing(core: _CoreProtocol) -> bool:
    options = core.options
    if not options.show_line_number:
        options.show_line_number = True
        options.show_total_lines = False
    elif not options.show_total_lines:
        options.show_total_lines = True
    else:
        options.show_line_number = False
        options.show_total_lines = False
    return True


def _log_transformations(core: _CoreProtocol) -> bool:
    with efablogger.lock:
        return _log_transformations_(core)


def _log_transformations_(core: _CoreProtocol) -> bool:
    if not core.transformations:
        efablogger.say(
            _(
                "Cannot show the effect of transformation rules "
                "because none were given."
            ),
            type_of_msg=efablogger.ERROR,
        )
        return False
    try:
        efablogger.say(
            _("Preparing the transformation-rules log."),
            type_of_msg=efablogger.INFO,
        )
        text = None
        for cmd in core.source.transformation_log_pipeline:
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
            core.player.stop()
            if get_args().scripted:
                log += "END OF LOG"
                efablogger.say(log, type_of_msg=efablogger.NORMAL_EXTENDED)
            else:
                efablogger.pager(
                    log,
                    title=_("Showing the transformation-rules log.")
                )
            return True
        else:
            efablogger.say(
                _(
                    "It seems the text source was not affected by the "
                    "transformation rules."
                ),
                type_of_msg=efablogger.INFO,
            )
            return False
    except Exception as e:
        efablogger.report_error(e)
        efablogger.say(
            _("The program cannot show the transformation-rules "
              "log."),
            type_of_msg=efablogger.ERROR,
        )
    return False


def _run_in_shell(core: _CoreProtocol, cmd: Optional[str] = None) -> bool:
    if get_args().scripted:
        return False

    if not cmd:
        return _open_shell(core)
    else:
        with efablogger.lock:
            cp = subprocess.run(
                shlex.split(cmd),
                stdout=efablogger.get_file(efablogger.NORMAL),
                stderr=efablogger.get_file(efablogger.NORMAL),
            )
            efablogger.separate(efablogger.NORMAL)
        return cp.returncode == 0


def _open_shell(core: _CoreProtocol) -> bool:
    if get_args().scripted:
        return False

    ret = True
    with efablogger.lock:
        efablogger.say(
            _("Entering the shell; close the shell to return to the program."),
            type_of_msg=efablogger.INFO,
        )
        efabuserinput.set_normal()
        try:
            subprocess.call(os.environ["COMSPEC" if WINDOWS else "SHELL"])
            print()
            efablogger.say(_("Resuming the program."), efablogger.INFO)
        except Exception as e:
            ret = False
            efablogger.report_error(e)
            efablogger.say(
                _("The program could not open a shell."),
                efablogger.ERROR
            )
    return ret


def _open_file(core: _CoreProtocol, name: str) -> bool:
    if not os.path.exists(name):
        efablogger.say(
            _("The file/directory %s does not exist.") % name, efablogger.ERROR
        )
        return False
    else:
        start_daemon(lambda: _open_file_aux(core, name))
        return True


def _open_file_aux(core: _CoreProtocol, name: str) -> None:
    try:
        if not os.path.exists(name):
            raise Exception(_("Cannot find file/directory: %s.") % name)
        efablogger.say(
            _("Opening %s in another window.") % name, efablogger.INFO
        )
        # In case you modify the following call, be VERY careful to ensure
        # sanitization.
        if not (LINUX or WINDOWS):
            raise InternalError(UNSUPPORTED_PLATFORM)
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
        with efablogger.lock:
            efablogger.report_error(e)
            efablogger.say(
                _("The program could not open file: %s") % name,
                efablogger.ERROR,
            )


def _open_input_file(core: _CoreProtocol) -> bool:
    input_file = core.source.filename
    if input_file is not None:
        return _open_file(core, input_file)
    else:
        with efablogger.lock:
            efablogger.say(_("No input file was given."), efablogger.ERROR)
            _show_input_command(core)
        return False


def _show_input_command(core: _CoreProtocol) -> bool:
    efablogger.say(
        _("The input command is:\n\n%s") % core.source.command,
        efablogger.INFO,
    )
    return True


def _choose_and_open_file(
    core: _CoreProtocol,
    file_list: List[str],
    no_file_msg=_("There are no files to edit.")
) -> bool:

    if not file_list:
        efablogger.say(no_file_msg, type_of_msg=efablogger.ERROR)
        return False

    if len(file_list) == 1:
        return _open_file(core, file_list[0])

    core.player.stop()

    with efablogger.lock:
        return _choose_and_open_file_(core, file_list)


def _choose_and_open_file_(core, file_list):

    efablogger.say(
        _("Choose file to edit:"), type_of_msg=efablogger.INTERACTION
    )

    n = 1
    s = ""
    for f in file_list:
        s += str(n) + ": " + f + "\n"
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
        c = efabuserinput.getch()
        if c.isdigit():
            if c == "0":
                efablogger.report_action_cancelled()
                return False
            elif int(c) >= 1 and int(c) <= len(file_list):
                f = file_list[int(c) - 1]
                return _open_file(core, f)


def _change_speed(core: _CoreProtocol, delta: int) -> bool:
    speed = core.options.speed + delta
    if speed >= MAXSPEED and delta > 0:
        efablogger.say(
            _("Cannot set a speed higher than the maximum (%s)") % MAXSPEED,
            type_of_msg=efablogger.INFO
        )
        return False
    elif speed <= MINSPEED and delta < 0:
        efablogger.say(
            _("Cannot set a speed lower than the  minimum (%s)") % MINSPEED,
            type_of_msg=efablogger.INFO
        )
        return False
    # The speed set here will not apply to a currently running instance of
    # espeak.
    core.options.speed = speed
    core.options.log("speed")
    return True


def _modify_option(options, name: str, *args: Iterable[str]) -> bool:
    if options.modify(name, *args):
        options.log(name, mandatory=(name in ['no-info', 'no_info']))
        return True
    else:
        return False


_in_command_loop = False


# The _command_loop function implements a hidden "shell" to send commands in
# the internal script language to the player. It is (and will likely always be)
# an undocumented feature for testing and debugging purposes. There is no
# default key binding to this function in the normal installation. If you want
# to use it, you should add a key binding to the "cmd" macro. (You can use the
# command-line switches --edit-key-bindings, --key-bindings and
# --add-key-bindings for that). I personally like to bind it to the ! sign.
# You can also think of this as if it were an Easter-egg :)


def _command_loop(core: _CoreProtocol) -> bool:
    global _in_command_loop

    if get_args().scripted:
        return False

    if _in_command_loop:
        efablogger.say(
            _(
                "The petition to enter the command loop was ignored "
                "because you are already in the command loop."
            ),
            efablogger.ERROR,
        )
        return False

    _in_command_loop = True

    core.player.stop()

    msg = _(
        "You have entered the command line mode, where you can interact with "
        "the program by entering commands in the internal scripting language."
    )
    msg += " " + (
        "In command mode, some functionalities (e.g. tracking events) might "
        "not work as usual."
    )
    efablogger.say(msg, efablogger.INFO_EXTENDED)

    msg = "\n" + _(
        "The internal scripting language is an undocumented feature, and it "
        "is subject to change. Use it at your own risk (and/or enjoyment)."
    )
    msg += " " + _(
        "WARNING: this is an experimental feature, not intended for "
        "normal users."
    )
    efablogger.say(msg, efablogger.INFO_EXTENDED)

    no_info, no_echo, muted = core.options.no_info, core.options.no_echo, False

    extended_prompt = _(
                "Enter \"exit\" to return to the normal mode. If you restart "
                "the player, you can press . (period) followed by Enter to "
                "stop the player and show this prompt again. Press ; "
                "(semicolon) followed by Enter to mute/unmute all printing to "
                "the screen from the player. Press , (comma) followed by "
                "Enter to allow a tracking event to proceed."
            )

    efablogger.say(extended_prompt, type_of_msg=efablogger.INFO_EXTENDED)

    while True:

        line = efabuserinput.getline(
            prompt=efablogger.get_prompt(type_of_msg=efablogger.INTERACTION)
        )
        efablogger.separate(type_of_msg=efablogger.INTERACTION)
        if not line or line.strip().endswith("."):
            core.player.stop()
            efablogger.say(
                extended_prompt, type_of_msg=efablogger.INFO_EXTENDED
            )
        elif line.strip().endswith(";"):
            muted = not muted
            if muted:
                core.options.no_info, core.options.no_echo = True, True
            else:
                core.options.no_info, core.options.no_echo = (
                    no_info, no_echo)
        elif line.strip().endswith(","):
            core.player.lock.release()
            time.sleep(0.1)
            core.player.lock.acquire()
        elif line.strip() == "exit":
            efablogger.say(
                _("You are returning to the normal mode."),
                efablogger.INFO,
            )
            break
        else:
            parsed_command = parse(line.strip())
            if parsed_command:
                process(core, parsed_command)
    _in_command_loop = False

    return True


# No matter how wonderful this program is, the user will want to get out of it
# sooner or later.
def _quit(core: _CoreProtocol, ask_for_confirmation=True) -> bool:
    ask = (
        ask_for_confirmation
        and not get_args().scripted
        and not core.options.quit_without_prompt
    )
    if (
        ask and efabuserinput.confirm_action(_("Do you really want to quit?"))
        or not ask
    ):
        terminate()
    return False


############################################################################

# Macros define a mapping from identifiers to (possibly compound) commands
# in the internal scripting language defined above.

# The scripting language is still subject to change, so for the time being we
# will keep it undocumented and hidden from the users. Macros act as a wrapper
# around the still undocumented scripting language.

# The program exposes a predefined set of actions (=macros), and the users can
# redefine their key bindings, but they cannot create nor change the macros
# themselves.

# However, the program will try to interpret undefined macro names as
# non-compound commands in the underlying scripting language. This is a hack,
# and we will keep it undocumented and hidden from the user for now.

# In future versions, we might allow the user to define macros and/or
# keyboard bindings pointing directly to commands in the scripting language
# (once its design is settled and well-proved).


MACRO_QUIT_ASK = "quit-ask"
MACRO_QUIT_NOW = "quit-now"

MSG_INVALID_MACRO = _("'%s' is not a valid action name.")

_macros = {
    MACRO_QUIT_NOW:
        "stop ; " + QUIT_CMD,

    MACRO_QUIT_ASK:
        "stop ; " + ASK_N_QUIT_CMD,

    "restart-and-stop":
        "modifyopt stop-after-current-line true ; restart",

    # We keep this macro from version 1, but it is not used by default in
    # version 2.
    "stop-and-reset-pointer":
        "stop ; resetpointer",

    # This is the new default binding for key "x" in version 2.
    "stop-and-reset":
        "stop ; resetpointer ; modifyopt stop-after-current-line false",

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
        % (SEARCH_PLAIN, SEARCH_CI),

    "search-plain-case-sensitive":
        "noecho find %s %s then showline"
        % (SEARCH_PLAIN, SEARCH_CS),

    "search-regex-case-insensitive":
        "noecho find %s %s then showline"
        % (SEARCH_REGEX, SEARCH_CI),

    "search-regex-case-sensitive":
        "noecho find %s %s then showline"
        % (SEARCH_REGEX, SEARCH_CS),

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
        "noecho noupdateplayer goprevchange then restart and "
        "modifyopt stop-after-current-line true and showline",

    "next-change":
        "noecho noupdateplayer gonextchange then restart and "
        "modifyopt stop-after-current-line true and showline",

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
  "toggle", "restart", "first", "last", "next", "previous", "reload", "cmd"
]:
    _macros[m] = m

# We will allow macro names to be surrounded by brackets for backward
# compatibility, but it is not mandatory now. Let's use the
# quick-and-dirty way, and just duplicate the keys. (Not a big dict.)
for m in list(_macros.keys()):
    _m = "<%s>" % m
    _macros[_m] = _macros[m]


def is_macro(name: str) -> bool:
    return name in _macros


MALFORMED_COMMAND = _("The following command is wrong: %s. Reported error "
                      "is: %s.")
WRONG_COMMAND = _("The following command is wrong: %s")
UNSUCCESFUL_COMMAND = _("The following command failed: %s. Reported error "
                        "is: %s.")


_AtomicParsedCommand = Tuple[str, ...]
_PrefixedParsedCommand = Tuple[str, "_ParsedCommand"]
_DyadicParsedCommand = Tuple[str, "_ParsedCommand", "_ParsedCommand"]
_ParsedCommand = Union[
    _AtomicParsedCommand, _PrefixedParsedCommand, _DyadicParsedCommand
]


def parse(cmd: str) -> Optional[_ParsedCommand]:
    cmd = cmd.strip()

    if not cmd:
        return None

    if is_macro(cmd):
        cmd = _macros[cmd]

    try:
        ret = _parse(shlex.split(cmd))
        if not ret:
            efablogger.say(WRONG_COMMAND % cmd, type_of_msg=efablogger.ERROR)
        return ret
    except ValueError as e:
        efablogger.say(
            MALFORMED_COMMAND % (cmd, e),
            type_of_msg=efablogger.ERROR
        )
        return None


def _parse(cmd: List[str]) -> Optional[_ParsedCommand]:
    if not cmd:
        return None
    elif CMD_SEPARATOR_LOW in cmd:
        return _parse_with_separator(CMD_SEPARATOR_LOW, cmd)
    elif CMD_SEPARATOR_THEN in cmd:
        return _parse_with_separator(CMD_SEPARATOR_THEN, cmd)
    elif CMD_SEPARATOR_ONMOVETHEN in cmd:
        return _parse_with_separator(CMD_SEPARATOR_ONMOVETHEN, cmd)
    elif CMD_SEPARATOR_HIGH in cmd:
        return _parse_with_separator(CMD_SEPARATOR_HIGH, cmd)
    elif cmd[0] in _prefixes:
        return _parse_with_prefix(cmd)
    else:
        ret = _parse_simple(cmd)
        return tuple(ret) if ret else None


def _parse_with_separator(
    separator: str, cmd: List[str]
) -> Optional[_ParsedCommand]:

    n = cmd.index(separator)
    branch1 = _parse(cmd[0:n])
    branch2 = _parse(cmd[n+1:])
    if branch1 and branch2:
        return (separator, branch1, branch2)
    return None


def _parse_with_prefix(cmd: List[str]) -> Optional[_PrefixedParsedCommand]:
    branch = _parse(cmd[1:])
    if branch:
        return (cmd[0], branch)
    return None


def _parse_simple(cmd: List[str]) -> Optional[List[str]]:

    if cmd is None:
        return None
    else:
        verb, *args = cmd

        if not args and verb in (
            _commands_with_no_args + _commands_with_or_without_args
        ):
            return cmd
        else:
            return _parse_simple_command_with_args(cmd, verb, args)


def _parse_simple_command_with_args(
    cmd: List[str], verb: str, args: List[str]
) -> Optional[List[str]]:

    if verb == "sh":
        return cmd if len(args) == 1 else None
    elif verb == "find":
        return _parse_find(cmd, args)
    elif verb == "info":
        return cmd if args else None
    elif verb == "modifyopt":
        return _parse_modify_opt(cmd, args)
    elif verb == "getopt":
        if not args:
            return None
        return cmd if len(args) == 1 else None
    elif len(args) == 1:
        if verb in _commands_which_accept_an_int:
            if verb == "changespeed":
                return cmd if re.match(r"[+-]?\d+$", args[0]) else None
            elif args[0].isdigit() and int(args[0]) > 0:
                return cmd
            return None
        elif verb == "openfile":
            return cmd
    return None


def _parse_find(cmd: List[str], args: List[str]) -> Optional[List[str]]:
    if len(args) > 3:
        return None
    if len(args) >= 2 and args[1] not in [SEARCH_CI, SEARCH_CS]:
        return None
    if len(cmd) >= 1 and args[0] not in [SEARCH_PLAIN, SEARCH_REGEX]:
        return None
    if len(args) == 3 and args[0] == SEARCH_REGEX:
        try:
            re.compile(args[2])
        except Exception as e:
            efablogger.say(
                MALFORMED_COMMAND % (cmd, e),
                type_of_msg=efablogger.ERROR
            )
            return None
    return cmd


def _parse_modify_opt(cmd: List[str], args: List[str]) -> Optional[List[str]]:
    if not args:
        return None
    if len(args) == 1:
        return cmd
    if len(args) > 2:
        return None
    return cmd


def process(core: _CoreProtocol, cmd: _ParsedCommand) -> bool:
    if not cmd:
        return False
    if cmd[0] in [CMD_SEPARATOR_HIGH, CMD_SEPARATOR_LOW]:
        cmd = cast(_DyadicParsedCommand, cmd)
        return _process_separator(core, cmd)
    elif cmd[0] == CMD_SEPARATOR_THEN:
        cmd = cast(_DyadicParsedCommand, cmd)
        return _process_then(core, cmd)
    elif cmd[0] == CMD_SEPARATOR_ONMOVETHEN:
        cmd = cast(_DyadicParsedCommand, cmd)
        return _process_onmovethen(core, cmd)
    elif cmd[0] == CMD_PREFIX_NOECHO:
        cmd = cast(_PrefixedParsedCommand, cmd)
        return _process_noecho(core, cmd)
    elif cmd[0] == CMD_PREFIX_NOINFO:
        cmd = cast(_PrefixedParsedCommand, cmd)
        return _process_noinfo(core, cmd)
    elif cmd[0] == CMD_PREFIX_NOUPDATEPLAYER:
        cmd = cast(_PrefixedParsedCommand, cmd)
        return _process_noupdateplayer(core, cmd)
    else:
        cmd = cast(_AtomicParsedCommand, cmd)
        return _process_simple(core, cmd)


def _process_separator(core: _CoreProtocol, cmd: _DyadicParsedCommand) -> bool:
    process(core, cmd[1])
    return process(core, cmd[2])


def _process_then(core: _CoreProtocol, cmd: _DyadicParsedCommand) -> bool:
    if process(core, cmd[1]):
        return process(core, cmd[2])
    return False


def _process_onmovethen(
    core: _CoreProtocol, cmd: _DyadicParsedCommand
) -> bool:

    ct = core.state.pointer
    process(core, cmd[1])
    if ct != core.state.pointer:
        return process(core, cmd[2])
    return False


def _process_noecho(core: _CoreProtocol, cmd: _PrefixedParsedCommand) -> bool:
    b = core.options.no_echo
    core.options.no_echo = True
    ret = process(core, cmd[1])
    core.options.no_echo = b
    return ret


def _process_noinfo(core: _CoreProtocol, cmd: _PrefixedParsedCommand) -> bool:
    b = core.options.no_info
    core.options.no_info = True
    ret = process(core, cmd[1])
    core.options.no_info = b
    return ret


def _process_noupdateplayer(
    core: _CoreProtocol, cmd: _PrefixedParsedCommand
) -> bool:
    b = core.options.no_update_player
    core.options.no_update_player = True
    ret = process(core, cmd[1])
    core.options.no_update_player = b
    return ret


def _process_simple(core: _CoreProtocol, cmd: _AtomicParsedCommand) -> bool:
    verb, *args = cmd
    try:
        if verb in _bindings_general:
            action = _bindings_general[verb]
            return action(core, *args)
        elif verb in _bindings_player:
            if core.player.text_is_loaded():
                action = _bindings_player[verb]
                return action(core, *args)
            else:
                return False
        else:
            raise KeyError(_("Unknown command"))
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        efablogger.say(
            UNSUCCESFUL_COMMAND % (verb, e),
            type_of_msg=efablogger.ERROR
        )
        return False


def contains_quit(what: Union[str, _ParsedCommand]) -> bool:
    if isinstance(what, str):
        return what in [QUIT_CMD, ASK_N_QUIT_CMD]
    elif what[0] in _non_conditional_separators:
        # Both the antecedent and the consequent get executed.
        what = cast(_DyadicParsedCommand, what)
        return contains_quit(what[1]) or contains_quit(what[2])
    elif what[0] in _separators:
        # We cannot be sure the consequent will be executed,
        # so only check the antededent
        return contains_quit(what[1])
    elif what[0] in _prefixes:
        return contains_quit(what[1])
    else:
        # Just check the verb of the command.
        return contains_quit(what[0])


# Bindings between keys and macros. In a future version, binding directly to
# commands in the scripting language will be possible.

DEFAULT_BINDINGS = {
    "Q": MACRO_QUIT_NOW,
    "q": MACRO_QUIT_ASK,
    " ": "toggle",
    "a": "restart",
    "A": "restart-and-stop",
    "x": "stop-and-reset",
    "V": "first-stop",
    "v": "first",
    "M": "last-stop",
    "m": "last",
    "N": "next-stop",
    "n": "next",
    "B": "stop-or-previous",
    "b": "previous",
    ".": "toggle-stop-after-current-line",
    ",": "toggle-stop-after-each-line",
    "S": "toggle-apply-subst",
    "D": "toggle-show-subst",
    "u": "log-subst",
    "j": "log-transform",
    "l": "cycle-line-number",
    "w": "show-line",
    "f": "search-plain-case-insensitive",
    "F": "search-plain-case-sensitive",
    "r": "search-regex-case-insensitive",
    "R": "search-regex-case-sensitive",
    "/": "search",
    "t": "find-next",
    "T": "find-next-stop",
    "e": "find-prev",
    "E": "find-prev-stop",
    "g": "go-line",
    "<": "prev-change",
    ">": "next-change",
    "*": "random",
    "+": "faster",
    "-": "slower",
    "o": "open-input-file",
    "O": "open-input-file-stop",
    "s": "open-subst",
    ":": "open-transform",
    "_": "open-cl-monitored-file",
    "c": "open-shell",
    "L": "reload",
    "C": "check-files",
    "?": "choose-tracking-mode",
    ")": "choose-sequence-mode",
    "=": "choose-feedback-mode",
    "0": "special-mode",
    "1": "normal-mode",
    "I": "show-input-cmd-stop",
    "i": "show-input-cmd",
}


_bindings: Dict[str, str] = DEFAULT_BINDINGS
_parsed_bindings: Dict[str, _ParsedCommand] = {}
_key_is_bound_to_quit: Dict[str, bool] = {}


def set_bindings(key_bindings: Dict[str, str]) -> None:
    global _bindings
    global _parsed_bindings

    _bindings = key_bindings
    _parsed_bindings = {}


def get_parsed_command(ch: str) -> Optional[_ParsedCommand]:
    if ch not in _parsed_bindings:
        if ch in _bindings:
            parsed_command = parse(_bindings[ch])
            if parsed_command:
                _parsed_bindings[ch] = parsed_command
                return parsed_command
            return None
        return None
    return _parsed_bindings[ch]


def is_bound_to_quit_command(ch: str) -> bool:
    if ch not in _key_is_bound_to_quit:
        parsed_command = get_parsed_command(ch)
        if not parsed_command:
            return False
        _key_is_bound_to_quit[ch] = contains_quit(parsed_command)
    return _key_is_bound_to_quit[ch]
