#!/usr/bin/env python3

# EFABRULES: a companion module for EFABULOR and EFABTRANS
# Copyright (C) 2021-2023 Esteban Flamini <http://estebanflamini.com>

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

__version__ = "0.99"

import gettext
import os
import sys
import traceback
import re
import efabregex
from ast import literal_eval

# Localisation should be easy
DOMAIN = "efabrules"
if (
  "TEXTDOMAINDIR" in os.environ
  and gettext.find(DOMAIN, os.environ["TEXTDOMAINDIR"])
):
    gettext.install(DOMAIN, os.environ["TEXTDOMAINDIR"])
elif gettext.find(DOMAIN, sys.path[0]):
    gettext.install(DOMAIN, sys.path[0])
else:
    gettext.install(DOMAIN)


class error(Exception):
    pass


# Currently, the only extended replacement constructs are {uc:...} and {lc:...}
EXTENDED_REPL = r"(?i)({[ul]c:.+?})"


class rule(object):
    def __init__(
        self,
        filename,
        definition,
        regex_object,
        pattern,
        repl,
        allow_extended_repl=True,
    ):
        self.filename = filename
        self.definition = definition
        self.regex_object = regex_object
        self.pattern = pattern
        self.repl = repl
        if allow_extended_repl and re.search(EXTENDED_REPL, repl):
            self._repl = lambda m: self._expand_extended_replacement(
                m, re.split(EXTENDED_REPL, repl)
            )
        else:
            self._repl = lambda m: m.expand(repl)

    def expand(self, m):
        return self._repl(m)

    def _expand_extended_replacement(self, m, parts):
        s = ""
        for part in parts:
            if re.fullmatch(EXTENDED_REPL, part):
                if part[0:4].lower() == "{uc:":
                    s += m.expand(part[4:-1]).upper()
                else:  # It can only be {lc: due to the way parts was created
                    s += m.expand(part[4:-1]).lower()
            else:
                s += m.expand(part)
        return s


_default_replacement = ""


def escape_backlashes(what):
    return what.replace("\\", "\\\\")


def set_default_replacement(what):
    global _default_replacement
    _default_replacement = escape_backlashes(what)


errors_detected = False


def _report_wrong_rule(filename, definition, why):
    global errors_detected

    print(
        _("Wrong rule in file: %s. Reason is: %s.\n") % (filename, why),
        file=sys.stderr
    )
    print(definition, file=sys.stderr)
    print(file=sys.stderr)
    errors_detected = True


def process_rules(
    filename,
    content,
    rule_list,
    clean_before=True,
    context_allows_substitutions=True
):
    global errors_detected

    if clean_before:
        content = content.split("\n")
        content = list(map(str.strip, content))
        # Delete comment lines
        content = [x for x in content if not x or x[0] != "#"]
        content = "\n".join(content).strip()
    if not content:
        return False
    errors_detected = False
    for block in re.split(r"\n{2,}", content):
        lines = block.split("\n")
        if len(lines) == 1:
            _process_one_line_block(
                filename, lines[0], rule_list, context_allows_substitutions
            )
        elif not context_allows_substitutions:
            for line in lines:
                _process_one_line_block(filename, line, rule_list, False)
        elif len(lines) == 2:
            _process_two_line_block(filename, block, lines, rule_list)
        else:
            for line in lines:
                _process_substitution_rule(filename, line, rule_list)
    return not errors_detected


RULE_INVALID_FLAGS = _("invalid flags")
RULE_WRONG_SUBSTITUTION = _("wrong substitution rule")
RULE_UNTERMINATED = _("unterminated regular expression rule")
RULE_MUST_BE_IN_12LINE_BLOCK = _(
    "simple-match and plain text rules must be used in one- or two-line block"
)
RULE_AMBIGUOUS_TWO_LINE_BLOCK = _(
    "two-line block is ambiguous (missing separating new line?)"
)
RULE_WRONG_TWO_LINE_BLOCK = _(
    "two-line block’s second line must be plain text"
)
RULE_NOT_ALLOWED = _("this rule is not allowed in this context")


def _process_substitution_rule(filename, line, rule_list):
    if efabregex.is_substitution(line):
        if efabregex.contains_invalid_flags(line):
            _report_wrong_rule(filename, line, RULE_INVALID_FLAGS)
        else:
            try:
                regex_object, pattern, repl = efabregex.compile_substitution(
                    line
                )
                new_rule = rule(filename, line, regex_object, pattern, repl)
                rule_list.append(new_rule)
            except efabregex.error as e:
                _report_wrong_rule(filename, line, e)
    elif efabregex.is_pattern(line):
        if efabregex.contains_invalid_flags(line):
            # Perhaps trying to create a substitution rule and omitted the
            # closing delimiter
            _report_wrong_rule(filename, line, RULE_UNTERMINATED)
        else:
            _report_wrong_rule(filename, line, RULE_MUST_BE_IN_12LINE_BLOCK)
    elif efabregex.is_unterminated(line):
        _report_wrong_rule(filename, line, RULE_UNTERMINATED)
    elif efabregex.is_possibly_wrong_substitution(line):
        _report_wrong_rule(filename, line, RULE_WRONG_SUBSTITUTION)
    else:
        # No chance to interpret the line as a regex, it looks more like a
        # plain text rule
        _report_wrong_rule(filename, line, RULE_MUST_BE_IN_12LINE_BLOCK)


def _process_one_line_block(
  filename,
  line,
  rule_list,
  context_allows_substitutions
):
    regex = None
    if efabregex.is_pattern(line):
        if efabregex.contains_invalid_flags(line):
            _report_wrong_rule(filename, line, RULE_INVALID_FLAGS)
            return
        else:
            regex = line
    elif efabregex.is_substitution(line):
        if context_allows_substitutions:
            _process_substitution_rule(filename, line, rule_list)
        else:
            _report_wrong_rule(filename, line, RULE_NOT_ALLOWED)
        return
    elif efabregex.is_unterminated(line):
        _report_wrong_rule(filename, line, RULE_UNTERMINATED)
        return
    elif efabregex.is_possibly_wrong_substitution(line):
        _report_wrong_rule(filename, line, RULE_WRONG_SUBSTITUTION)
        return
    else:  # The line is probably plain text
        regex = efabregex.create_match(re.escape(line))
    if regex:
        try:
            regex_object, pattern = efabregex.compile(regex)
            new_rule = rule(
                filename,
                line,
                regex_object,
                pattern,
                _default_replacement
            )
            rule_list.append(new_rule)
        except efabregex.error as e:
            _report_wrong_rule(filename, line, e)
    else:
        traceback.print_stack()
        sys.exit("Internal error while processing rule: %s" % line)


def _process_two_line_block(filename, block, lines, rule_list):
    if efabregex.is_substitution(lines[0]):
        if efabregex.is_substitution(lines[1]):
            _process_substitution_rule(filename, lines[0], rule_list)
            _process_substitution_rule(filename, lines[1], rule_list)
        else:
            _report_wrong_rule(filename, block, RULE_AMBIGUOUS_TWO_LINE_BLOCK)
    elif efabregex.is_regex(lines[1]):
        _report_wrong_rule(filename, block, RULE_WRONG_TWO_LINE_BLOCK)
    elif efabregex.is_possibly_wrong_substitution(lines[0]):
        _report_wrong_rule(filename, block, RULE_AMBIGUOUS_TWO_LINE_BLOCK)
    elif efabregex.is_possibly_wrong_substitution(lines[1]):
        _report_wrong_rule(filename, block, RULE_AMBIGUOUS_TWO_LINE_BLOCK)
    elif efabregex.is_unterminated(lines[0]):
        _report_wrong_rule(filename, block, RULE_AMBIGUOUS_TWO_LINE_BLOCK)
    elif efabregex.is_unterminated(lines[1]):
        _report_wrong_rule(filename, block, RULE_AMBIGUOUS_TWO_LINE_BLOCK)
    else:
        # The second line can only be plain text (as required) because of the
        # test immediately above.
        repl = escape_backlashes(lines[1])
        if efabregex.is_pattern(lines[0]):
            if efabregex.contains_invalid_flags(lines[0]):
                _report_wrong_rule(filename, block, RULE_INVALID_FLAGS)
                return
            regex = lines[0]
        else:
            # It is neither a pattern nor a substitution (first test above); it
            # can only be plain text
            regex = efabregex.create_match(re.escape(lines[0]))
        try:
            regex_object, pattern = efabregex.compile(regex)
            new_rule = rule(
                filename,
                block,
                regex_object,
                pattern,
                repl,
                allow_extended_repl=False
            )
            rule_list.append(new_rule)
        except efabregex.error as e:
            _report_wrong_rule(filename, block, e)


RULE_NOT_APPLIED = _(
    "The rule is wrong and was not applied: %s\n\nThe reason is: %s"
)


def sub(rule, text, repl=None):
    # use _repl, so extended replacements will be applied
    repl = repl or rule._repl
    if repl is None:
        sys.exit(
            "Internal error while processing rule %s - no replacement given."
            % rule.definition
        )
    try:
        return re.sub(rule.regex_object, repl, text)
    except re.error as e:
        raise error(RULE_NOT_APPLIED % (rule.definition, e))


if __name__ == "__main__":
    print(
        _(
            "This module contains functions to be used by other modules, and "
            "is not supposed to be called directly by the user."
        )
    )
