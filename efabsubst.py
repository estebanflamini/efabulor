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

import efabrules
import efablogger
from efabargs import get_args


_NO_SECTION = _(
    "Substitution rules cannot contain sections in this version: %s."
)
_ERROR_READING_RULES = _(
    "An error has occurred while trying to read substitution rules file: %s."
)
_FILE_NOT_APPLIED = _("The substitution file (%s) will not be applied.")
_NEW_SUBST_LOADED = _("New substitutions were loaded.")
_NO_RULES_GIVEN = _(
    "Cannot show the effect of substitution rules because none were given."
)
_NOT_APPLIED = _("Substitution rules are not being applied.")
_NOT_THIS_LINE = _("No substitutions were applied to this line.")
_SHOWING_HIST = _("Showing the substitution history.")

_SECTION_PATTERN = r"^\s*(\[[^[].*\])\s*$"
_END_OF_LOG = "END OF LOG"
_RULE = "rule"
_RESULT = "result"


class Substitutions:

    def __init__(self, rule_files, options):
        self._rule_files = rule_files
        self._options = options
        self._rules = []
        self._hist = []
        self._loaded = False

    def rule_files(self):
        return self._rule_files

    def load(self, force=False):
        if self._loaded and not force:
            return
        self._rules = []
        for filename in self._rule_files:
            try:
                with open(
                    filename, "r", encoding=self._options.config_encoding
                ) as f:
                    content = f.read()
                    # This will be removed if and when I implement protection
                    # rules directly within efabrules. (Currently, protection
                    # rules are implemented within efabtrans.)
                    m = re.search(
                        _SECTION_PATTERN, content, flags=re.MULTILINE
                    )
                    if m:
                        raise Exception(_NO_SECTION % m.group(1))
            except Exception as e:
                with efablogger.lock:
                    efablogger.say(
                        _ERROR_READING_RULES % filename,
                        type_of_msg=efablogger.ERROR
                    )
                    efablogger.report_error(e)
                    efablogger.say(
                        _FILE_NOT_APPLIED % filename,
                        type_of_msg=efablogger.INFO,
                    )
                continue
            efabrules.process_rules(filename, content, self._rules)
        self._loaded = True

    def reload(self):
        efablogger.say(_NEW_SUBST_LOADED, type_of_msg=efablogger.INFO)
        self.load(force=True)

    def apply(self, line):
        # Initialize the substitution history with the original line
        self._hist = [{_RULE: None, _RESULT: line}]

        for rule in self._rules:
            line_bak = line
            try:
                line = efabrules.sub(rule, line)
            except efabrules.error as e:
                efablogger.report_error(e)

            if line_bak != line:
                self._hist.append({_RULE: rule, _RESULT: line})

        return line

    def show_log(self, player):
        if not self._rules:
            efablogger.say(_NO_RULES_GIVEN, type_of_msg=efablogger.INFO)
            return False
        if not self._options.apply_subst:
            efablogger.say(_NOT_APPLIED, type_of_msg=efablogger.INFO)
            return False
        if len(self._hist) == 1:
            efablogger.say(_NOT_THIS_LINE, type_of_msg=efablogger.INFO)
            return False
        player.stop()
        s = ""
        for substitution in self._hist:
            if substitution[_RULE] is not None:
                s += substitution[_RULE].filename + "\n"
                s += substitution[_RULE].definition + "\n"
            s += substitution[_RESULT]
            s += "\n\n"
        if get_args().scripted:
            s += _END_OF_LOG
            efablogger.say(s, type_of_msg=efablogger.NORMAL_EXTENDED)
        else:
            efablogger.pager(
                s,
                title=_SHOWING_HIST,
                wrap=True
            )
        return True
