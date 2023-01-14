#!/usr/bin/env python3

# EFABUCW: a simple wrapper for unoconv
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

import sys
import os
import argparse
import subprocess
import gettext
import re


# Localisation should be easy
DOMAIN = "efabucw"
if (
  "TEXTDOMAINDIR" in os.environ
  and gettext.find(DOMAIN, os.environ["TEXTDOMAINDIR"])
):
    gettext.install(DOMAIN, os.environ["TEXTDOMAINDIR"])
elif gettext.find(DOMAIN, sys.path[0]):
    gettext.install(DOMAIN, sys.path[0])
else:
    gettext.install(DOMAIN)


def get_valid_formats():
    try:
        output = subprocess.check_output(
            ["unoconv", "--show"], text=True, stderr=subprocess.STDOUT
        )
        output = output.split("\n")
        output = [x for x in output if x]
        output = [x for x in output if re.match(r"\s*\w+\s+-\s+", x)]
        output = list(map(str.split, output))
        output = [x[0] for x in output if re.match(r"\w+", x[0])]
        return output
    except Exception as e:
        if isinstance(e, subprocess.CalledProcessError):
            print(e.output.strip(), file=sys.stderr)
        print(
            _("Could not determine valid output formats. Reported error is: "
              "%s") % e,
            file=sys.stderr,
        )
        sys.exit(1)


MAX_RETRIES = 10
TIMEOUT = 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("infile")
    parser.add_argument("-f", "--fmt", default="txt")
    args = parser.parse_args()

    if not os.path.isfile(args.infile):
        sys.exit(_("File %s does not exist.") % args.infile)

    if args.fmt not in get_valid_formats():
        sys.exit(_("%s is not a valid output format.") % args.fmt)

    cmd = [
        "unoconv",
        "-f",
        args.fmt,
        "--stdout",
        "--timeout",
        str(TIMEOUT),
        args.infile,
    ]

    for n in range(MAX_RETRIES):
        try:
            output = subprocess.run(
                cmd,
                check=True,
                capture_output=True
            ).stdout
            sys.stdout.buffer.write(output)
            break
        except Exception as e:
            if n == MAX_RETRIES - 1:
                if isinstance(e, subprocess.CalledProcessError):
                    sys.stderr.buffer.write(e.stderr.strip())
                print(
                    _("Text conversion failed. Reported error is: %s") % e,
                    file=sys.stderr,
                )
                sys.exit(1)


if __name__ == "__main__":
    main()
else:
    print(_("This module is not for import."), file=sys.stderr)
    sys.modules[__name__] = None
