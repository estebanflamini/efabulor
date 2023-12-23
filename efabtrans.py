#!/usr/bin/env python3

# EFABTRANS: a simple, configurable stream editor program to be used
# (mainly) as a companion to EFABULOR
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

__version__ = "1.0"

import os
import sys
import re
import argparse
import locale
import codecs
import re
import gettext
import traceback
import efabregex
import efabrules
import atexit


# Localisation should be easy
DOMAIN = "efabtrans"
if (
  "TEXTDOMAINDIR" in os.environ
  and gettext.find(DOMAIN, os.environ["TEXTDOMAINDIR"])
):
    gettext.install(DOMAIN, os.environ["TEXTDOMAINDIR"])
elif gettext.find(DOMAIN, sys.path[0]):
    gettext.install(DOMAIN, sys.path[0])
else:
    gettext.install(DOMAIN)


# FOR TRANSLATORS: The keypress used to answer YES to a yes/no question
YES_KEY = _("y")
# FOR TRANSLATORS: The keypress used to answer NO to a yes/no question
NO_KEY = _("n")


def confirm_action(prompt):
    print(prompt, end=" ")
    print("[%s/%s]" % (YES_KEY.lower(), NO_KEY.upper()), end=" ")
    sys.stdout.flush()
    answer = False
    while True:
        ch = input().strip().lower()
        if ch in [NO_KEY.lower(), YES_KEY.lower()]:
            answer = ch == YES_KEY
            break
        elif not ch:
            break
    return answer


output_encoding = None
input_encoding = None
config_encoding = None


rulesets = []


logfile = None


class ruleset(object):
    def __init__(self, do, donot):
        self.do = do
        self.donot = donot


def get_args():
    global args

    parser = argparse.ArgumentParser(prog="efabtrans.py")
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__
    )
    parser.add_argument("--encoding", default=None)
    parser.add_argument("--config-encoding", default=None)
    parser.add_argument(
        "--regex-flags",
        default="",
        metavar=_("<global flags for regular expressions>")
    )
    parser.add_argument(
        "-f",
        "-r",
        "--rules",
        "--transformation-rules",
        action="append",
        metavar=_("<rule configuration file>"),
        required=True,
        help=_(
            "This option can appear multiple times. Files will be processed "
            "in the given order."
        ),
    )
    parser.add_argument("--permissive", action="store_true", default=False)
    parser.add_argument(
        "--log",
        nargs="?",
        const="-",
        default=None,
        metavar=_("<file>"),
        help=_("Save log to this file (default is print to standard error)"),
    )
    parser.add_argument(
        "infile",
        nargs="?",
        default="-",
        metavar=_("<file to read input from>")
    )
    parser.add_argument(
        "outfile",
        nargs="?",
        default="-",
        metavar=_("<file to send output to>")
    )
    args = parser.parse_args()


def process_args():
    global logfile

    set_encoding()

    flags = args.regex_flags.strip().replace(" ", "")
    if flags:
        try:
            efabregex.set_default_flags(flags)
        except efabregex.error:
            sys.exit(
                _("Invalid global flags for regular expressions: %s") % flags
            )
    if "-" in args.rules:
        sys.exit(_("Cannot use - as a rule file."))
    for filename in args.rules:
        if not os.path.isfile(filename):
            if os.path.exists(filename):
                sys.exit(_("%s is not a file.") % filename)
            else:
                sys.exit(_("File %s does not exist.") % filename)
    if args.infile != "-":
        if not os.path.isfile(args.infile):
            if os.path.exists(args.infile):
                sys.exit(_("%s is not a file.") % args.infile)
            else:
                sys.exit(_("File %s does not exist.") % args.infile)
    if args.outfile != "-":
        confirm_overwrite(args.outfile)
    if args.log:
        if args.log != "-":
            confirm_overwrite(args.log)
            logfile = open(args.log, "w")
            atexit.register(close_logfile)
        else:
            logfile = sys.stderr


def close_logfile():
    logfile.close()


def confirm_overwrite(file_name):
    if os.path.exists(file_name):
        if not os.path.isfile(file_name):
            sys.exit(_("Cannot write to %s") % file_name)
        else:
            if not confirm_action(
                _("File %s already exists. Overwrite it?") % file_name
            ):
                sys.exit(_("Cancelled."))


def set_encoding():
    global input_encoding
    global output_encoding
    global config_encoding

    output_encoding = _set_encoding(args.encoding)
    input_encoding = (
        "utf-8-sig"
        if output_encoding.lower() in ["utf-8", "utf8"]
        else output_encoding
    )
    config_encoding = _set_encoding(args.config_encoding)


def _set_encoding(encoding):
    if encoding:
        try:
            codecs.encode("", encoding)
            return encoding
        except Exception as e:
            sys.exit(str(e))
    else:
        return locale.getdefaultlocale()[1]


def canonical_header(header):
    return header.strip().lower().replace("segment", "").replace(" ", "")


def set_rules():

    for filename in args.rules:
        try:
            with open(filename, "r", encoding=config_encoding) as f:
                content = f.read()
        except Exception as e:
            sys.exit(
                _("An error has occurred while reading file: %s. Reported "
                  "error is: %s") % (filename, e)
            )

        efabrules.set_default_replacement("\n")

        # Purge comments and extra spaces within lines
        content = content.split("\n")
        content = list(map(str.strip, content))
        content = [x for x in content if not x or x[0] != "#"]

        for x in content:
            x = x.replace(r"\[", "").replace(r"\]", "")
            if x and len(x) > 1 and (x[0] == "[" or x[-1] == "]"):
                if x[0] != "[" or x[-1] != "]":
                    sys.exit(
                        _("Error in file: %s. Unterminated header: %s")
                        % (filename, x)
                    )
                # Can only be [...]
                if canonical_header(x[1:-1]) not in ["do", "donot"]:
                    sys.exit(
                        _("Error in file: %s. Wrong header: %s")
                        % (filename, x)
                    )

        content = "\n".join(content).strip()

        content = re.split(
            r"^(\[.+?\])$", content, flags=re.MULTILINE
        )  # Split by section headers

        do = []
        donot = []

        target_list = do

        for block in content:
            if not block:
                # In case the splitting above returns any empty block
                pass
            elif "\n" not in block and block[0] == "[" and block[-1] == "]":
                ch = canonical_header(block[1:-1])
                if ch == "do":
                    if target_list is donot:
                        rulesets.append(ruleset(do, donot))
                        do = []
                        donot = []
                    elif len(do) > 0:
                        rulesets.append(ruleset(do, []))
                        do = []
                        donot = []
                    target_list = do
                elif ch == "donot":
                    if target_list is do:
                        if len(do) == 0:
                            sys.exit(
                                _(
                                    "Error in rule file: %s - a [donot] "
                                    "section without a corresponding [do] "
                                    "section."
                                ) % filename
                            )
                    elif len(donot) > 0:
                        sys.exit(
                            _(
                                "Error in rule file: %s - two consecutive "
                                "[donot] sections."
                            ) % filename
                        )
                    target_list = donot
                else:
                    sys.exit("Internal error: unfiltered malformed_header.")
            elif not block.strip():
                sys.exit(_("Empty section in rule file: %s") % filename)
            elif not efabrules.process_rules(
                filename,
                block.strip(),
                target_list,
                clean_before=False,
                context_allows_substitutions=target_list is do,
            ):
                if not args.permissive:
                    sys.exit(
                        _(
                            "Aborting due to error(s) found while processing "
                            "rule file: %s."
                        ) % filename
                    )
        rulesets.append(ruleset(do, donot))


def openreader():
    if args.infile == "-":
        return sys.stdin.buffer
    return open(args.infile, "rb")


def openwriter():
    if args.outfile == "-":
        return sys.stdout.buffer
    return open(args.outfile, "wb")


def process():
    try:
        with openwriter() as outfile:
            with openreader() as infile:
                text = codecs.decode(
                    infile.read(), encoding=input_encoding, errors="replace"
                )
                for rs in rulesets:
                    text = process_ruleset(rs, text)
                outfile.write(
                    codecs.encode(
                        text,
                        encoding=output_encoding,
                        errors="replace"
                    )
                )
    except IOError as e:
        sys.exit(_("Input/output error: %s.") % e)


def process_ruleset(ruleset, text):
    global recalculate_protected_areas

    recalculate_protected_areas = True
    for rule in ruleset.do:
        try:
            # Create a set spanning all positions within the text which are
            # protected by 'do not' rules
            if recalculate_protected_areas:
                protected_area = set()
                for protection_rule in ruleset.donot:
                    for m in protection_rule.regex_object.finditer(text):
                        protected_span = m.span()
                        log_protection_rule(protection_rule, protected_span, m)
                        # E.g., if a match spans the range (10, 15), this line
                        # will add {10, 11, 12, 13, 14} to protected_area
                        protected_area.update(range(*protected_span))
            # Apply the substitution rule to unprotected areas in the text
            # If a substitution was actually performed, delete protected_area,
            # so it is updated in next iteration
            recalculate_protected_areas = False
            text = efabrules.sub(
                rule,
                text,
                repl=lambda m: replace_if_not_protected(
                    rule,
                    m,
                    protected_area
                ),
            )
        except efabrules.error as e:
            print(e, file=sys.stderr)
            print(file=sys.stderr)
    return text


def replace_if_not_protected(rule, m, protected_area):
    global recalculate_protected_areas

    log_substitution_rule_match(rule, m)
    if not protected_area.intersection(range(*m.span())):
        recalculate_protected_areas = True
        result = rule.expand(m)
        log_substitution_rule_applied(rule, result)
        return result
    else:
        log_substitution_rule_not_applied()
        return m.group()


def log_protection_rule(rule, span, m):
    if args.log:
        print(_("Filename: %s") % rule.filename, file=logfile)
        print(_("Protection rule: %s") % rule.pattern, file=logfile)
        print(_("Protected span: %s") % str(span), file=logfile)
        print(
            _("Protected text: %s") % repr(m.group()).strip("'"),
            file=logfile
        )
        print(file=logfile)


CONTEXT = 20


def log_substitution_rule_match(rule, m):
    if args.log:
        print(_("Filename: %s") % rule.filename, file=logfile)
        print(_("Substitution rule: %s") % rule.pattern, file=logfile)
        print(_("Replacement: %s") % rule.repl, file=logfile)
        print(_("Target span: %s") % str(m.span()), file=logfile)
        print(_("Target text: %s") % repr(m.group()), file=logfile)
        context = m.string[max(0, m.start()-CONTEXT): m.start()]
        context += "--->>>%s<<<---" % m.group()
        context += m.string[m.end(): min(len(m.string), m.end() + CONTEXT)]
        print(_("In context: %s") % repr(context).strip("'"), file=logfile)


def log_substitution_rule_applied(rule, result):
    if args.log:
        print(_("Replaced with: %s") % repr(result), file=logfile)
        print(file=logfile)


def log_substitution_rule_not_applied():
    if args.log:
        print(
            _(
                "The rule was not applied because the target span intersects "
                "a protected area."
            ),
            file=logfile,
        )
        print(file=logfile)


def main():
    get_args()
    process_args()
    set_rules()
    process()


if __name__ == "__main__":
    main()
else:
    print(_("This module is not for import."), file=sys.stderr)
    sys.modules[__name__] = None
