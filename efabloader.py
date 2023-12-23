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


import efabargs
import efabcore
import efabregex
import efablogger

from efabrto import RuntimeOptions


_CANNOT_FIND_FILE = _("The program cannot find the input file: %s")
_NO_READABLE_TEXT = _("The text source is empty or contains no readable text.")
_NO_READABLE_SEGMENTS = _("No readable segments were found.")

_WRONG_SEPARATOR_REGEX = _(
    "Wrong regular expression given for separator: %s"
)
_UNTERMINATED_SEPARATOR_REGEX = _(
    "Unterminated regular expression given for separator: %s"
)
_INVALID_SEPARATOR_FLAGS = _("Invalid flags given for separator: %s")
_SUBSTITUTION_SEPARATOR = _(
    "A substitution expression cannot be used as a separator: %s"
)
_WRONG_SEGMENTING_REGEX = _(
    "Wrong regular expression given for segmenting: %s"
)
_UNTERMINATED_SEGMENTING_REGEX = _(
    "Unterminated regular expression given for segmenting: %s"
)
_INVALID_SEGMENTING_FLAGS = _("Invalid flags given for segmenting: %s")
_SUBSTITUTION_SEGMENTING = _(
    "A substitution expression cannot be used for segmenting: %s"
)

_READING_FILE = _("Reading file: %s ...")
_READING_COMMAND = _("Reading output from: %s")
_UNABLE_TO_GET_MIMETYPE = _(
    "The program could not determine the mimetype of the file: %s"
)
_HINT = _(
    "Hint: perhaps the segmentation rule or separator given in the command "
    "line is wrong."
)


class TextLoadingError(Exception):
    pass


@dataclass
class InputSource:
    filename: Optional[str] = None
    command: Optional[str] = None
    pipeline: List[str] = field(default_factory=list)
    transformation_log_pipeline: List[str] = field(default_factory=list)
    segmenting_regex: Optional[str] = None
    separator_regex: Optional[str] = None


_lock = threading.RLock()

# If you modify the following functions, be VERY careful to ensure
# input_command is sanitized (shlex.quote where appropriate), to avoid a
# 'command injection'. load_text depends on receiving a sanitized input
# command.


def get_source(args, options):
    if args.do is not None:
        input_file = None
        # No sanitizing is possible here, it is up to the user
        input_command = _execute_in_shell(shlex.quote(args.do))
    elif args.file is not None:
        check_file_validity(args.file)
        input_file = args.file
        input_command = _input_command(args, options)

    for the_filter in args.preprocess:
        # No sanitizing is possible here, it is up to the user
        input_command += " | " + the_filter

    transformation = _transformation(args, options)
    if transformation:
        input_command += " | %s %s" % (EFABTRANS, transformation)
        transformation_log_pipeline = _create_input_pipeline(
            input_command + " --log"
        )
    else:
        transformation_log_pipeline = None

    input_pipeline = _create_input_pipeline(input_command)

    return InputSource(
        input_file,
        input_command,
        input_pipeline,
        transformation_log_pipeline,
        *_segmenting_mode(args)
    )


def _execute_in_shell(cmd):
    if LINUX:
        return "%s -c %s" % (os.environ["SHELL"], cmd)
    elif WINDOWS:
        return "cmd /C %s" % shlex.quote(args.do)
    else:
        raise InternalError(UNSUPPORTED_PLATFORM)


def _input_command(args, options):
    if _mimetype(args.file) == "text/plain":
        if LINUX:
            return "cat " + shlex.quote(args.file)
        elif WINDOWS:
            return "cmd /C type " + shlex.quote(args.file)
        else:
            raise InternalError(UNSUPPORTED_PLATFORM)
    else:
        if args.text_conversion_config:
            conversion_option = (
                "--config-file %s " % shlex.quote(
                    args.text_conversion_config
                )
            )
        else:
            conversion_option = ""
        return "%s %s --lang %s %s" % (
            EFABCONV,
            conversion_option,
            shlex.quote(options.lang),
            shlex.quote(args.file),
        )


# If you modify this function, be VERY careful to ensure
# _transformation_option is sanitized (shlex.quote where appropriate)
# to avoid a 'command injection'. load_text depends on receiving sanitized
# commands.

def _transformation(args, options):
    transformation = ""
    for fn in map(os.path.expanduser, args.transformation_rules):
        check_file_validity(fn)
        transformation += " -f %s " % shlex.quote(fn)
    if transformation:
        flags = args.regex_flags.strip().replace(" ", "")
        if flags:
            transformation = "--regex-flags %s %s " % (
                shlex.quote(flags),
                transformation,
            )
        transformation += "--encoding %s --config-encoding %s " % (
            shlex.quote(options.input_encoding),
            shlex.quote(options.config_encoding),
        )
    return transformation


def _segmenting_mode(args):

    what = args.separator or args.segment
    if not what:
        return None, None
    if efabregex.is_substitution(what):
        efabcore.terminate(
            (
                _SUBSTITUTION_SEPARATOR
                if what is args.separator
                else _SUBSTITUTION_SEGMENTING
            )
            % what
        )
    elif efabregex.is_unterminated(what):
        efabcore.terminate(
            (
                _UNTERMINATED_SEPARATOR_REGEX
                if what is args.separator
                else _UNTERMINATED_SEGMENTING_REGEX
            )
            % what
        )
    elif efabregex.contains_invalid_flags(what):
        efabcore.terminate(
            (
                _INVALID_SEPARATOR_FLAGS
                if what is args.separator
                else _INVALID_SEGMENTING_FLAGS
            )
            % what
        )
    elif efabregex.is_pattern(what):
        regex = what
    elif what is args.separator:
        return None, re.escape(translate_control_chars(what))
    else:
        regex = efabregex.create_match(what)
    try:
        regex_object, pattern = efabregex.compile(regex)
        if what is args.separator:
            return None, pattern
        else:
            return pattern, None
    except efabregex.error as e:
        efablogger.say(
            (
                _WRONG_SEPARATOR_REGEX
                if what is args.separator
                else _WRONG_SEGMENTING_REGEX
            )
            % what,
            type_of_msg=efablogger.ERROR,
        )
        efabcore.terminate(REPORTED_ERROR_MSG % e)


def _create_input_pipeline(cmd: str) -> list[str]:
    if isinstance(cmd, str):
        return _create_input_pipeline(shlex.split(cmd))
    elif "|" in cmd:
        n = cmd.index("|")
        return [cmd[0:n]] + _create_input_pipeline(cmd[n+1:])
    return [cmd]


def load_text(
    source: InputSource,
    options: RuntimeOptions,
    on_success: callable,
    on_error: callable
):
    if source.filename is not None:
        if not os.path.isfile(source.filename):
            on_error(
                TextLoadingError(_CANNOT_FIND_FILE % source.filename,)
            )
        else:
            efablogger.say(
                _READING_FILE % source.filename, type_of_msg=efablogger.INFO,
            )
    else:
        efablogger.say(
            _READING_COMMAND % source.command, type_of_msg=efablogger.INFO,
        )
    _load_text(source, options, on_success, on_error)


def _load_text(source, options, on_success, on_error):
    with _lock:
        try:
            def kill_process():
                process.terminate()

            text = None

            # input_pipeline should be already sanitized.
            for cmd in source.pipeline:
                process = _create_process(cmd, options)
                atexit.register(kill_process)
                text, errors = process.communicate(text)
                atexit.unregister(kill_process)
                if errors:
                    raise TextLoadingError(errors)
            lines = _split_text(source, text)
            on_success(text, lines)
        except Exception as e:
            on_error(e)
        finally:
            atexit.unregister(kill_process)


def _create_process(cmd, options):
    return subprocess.Popen(
        cmd,
        text=True,
        encoding=_input_encoding_sig(options.input_encoding),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _split_text(source, text):
    if not text.strip():
        raise TextLoadingError(_NO_READABLE_TEXT)
    else:
        lines = _segment(source, text)
        lines = list(map(str.strip, lines))
        lines = [x for x in lines if x]
        if not lines:
            msg = _NO_READABLE_SEGMENTS
            if source.segmenting_regex or source.separator_regex:
                msg += " " + _HINT
            raise TextLoadingError(msg)
    return lines


def _segment(source, text):
    if source.separator_regex:
        return re.split(source.separator_regex, text)
    elif source.segmenting_regex:
        lines = re.findall(source.segmenting_regex, text)
        if lines and isinstance(lines[0], tuple):
            lines = [x for sublist in lines for x in sublist]
        return lines
    else:
        return text.split("\n")


def _mimetype(filename):
    mt, error = _mimetype_aux(filename)
    if error:
        efablogger.report_error(error)
        efablogger.say(
            _UNABLE_TO_GET_MIMETYPE % filename, type_of_msg=efablogger.ERROR,
        )
    return mt


def _mimetype_aux(filename):
    if LINUX:
        return _mimetype_os(filename)
    elif filename.lower().endswith(".txt"):
        return "text/plain", None
    else:
        return None, None


def _mimetype_os(filename):
    try:
        # Sanitizing filename is not necessary, provided the
        # command is given as an array. Be VERY careful to provide
        # sanitization in case you make the following call through
        # a shell.
        return subprocess.run(
            ["mimetype", "-b", "-L", filename],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip(), None
    except Exception as e:
        return None, e


def _input_encoding_sig(encoding):
    return "utf-8-sig" if encoding.lower() in ["utf-8", "utf8"] else encoding


def check_file_validity(filename, allow_dir=False):
    if not os.path.exists(filename):
        efabcore.terminate(_("The file %s does not exist.") % filename)
    elif not allow_dir and not os.path.isfile(filename):
        efabcore.terminate(_("%s is not a file.") % filename)
