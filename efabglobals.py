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


import os
import re
import sys
import time
import queue
import shlex
import atexit
import codecs
import locale
import signal
import gettext
import argparse
import platform
import textwrap
import threading
import traceback
import subprocess
from random import randint
from ast import literal_eval
from difflib import SequenceMatcher
from dataclasses import dataclass, replace, field

from typing import (
    List, Tuple, Dict, Callable, Optional, Any, TypeVar, Union, Iterable,
    cast, TYPE_CHECKING
)

# This is to accommodate older versions of Python:
if TYPE_CHECKING:
    from typing_extensions import Protocol, ParamSpec, Concatenate
else:
    @dataclass
    class ParamSpec:
        name: str
        args = None
        kwargs = None

    class Concatenate(Tuple):
        pass

    class Protocol:
        pass


try:
    import psutil

    PSUTIL_INSTALLED = True
except ModuleNotFoundError:
    PSUTIL_INSTALLED = False

# Additional modules are imported below after determining host platform

PROGNAME = "efabulor"

EFABTRANS = sys.path[0] + "/efabtrans.py"
EFABCONV = sys.path[0] + "/efabconv.py"

locale.setlocale(locale.LC_ALL, "")

# Localisation should be easy
if (
  "TEXTDOMAINDIR" in os.environ
  and gettext.find(PROGNAME, os.environ["TEXTDOMAINDIR"])
):
    gettext.install(PROGNAME, os.environ["TEXTDOMAINDIR"])
elif gettext.find(PROGNAME, sys.path[0]):
    gettext.install(PROGNAME, sys.path[0])
else:
    gettext.install(PROGNAME)

PLATFORM = platform.system()

if PLATFORM in [
    "Linux",
    "Darwin",
]:
    # We will think positive, and assume this will run under macOS and related
    # OSs.
    import termios

    try:
        import readline
    except ModuleNotFoundError:
        pass

    LINUX = True
    WINDOWS = False
elif PLATFORM == "Windows":
    import msvcrt

    LINUX = False
    WINDOWS = True
    EFABTRANS = sys.executable + " " + EFABTRANS.replace("\\", "/")
    EFABCONV = sys.executable + " " + EFABCONV.replace("\\", "/")
else:
    sys.exit(
        _("Fatal error: could not determine host platform or it is "
          "unsupported.")
    )

UNSUPPORTED_PLATFORM = _("Unsupported operation for platform: %s.") % PLATFORM

# FOR TRANSLATORS: This is the keypress used to answer YES to a yes/no question
YES_KEY = _("y")
# FOR TRANSLATORS: This is the keypress used to answer NO to a yes/no question
NO_KEY = _("n")

DEFAULT_ERROR_RETURNCODE = 1

SYSTEM_ENCODING = locale.getdefaultlocale()[1] or "UTF-8"

DEFAULT_SPEED = 180
MAXSPEED = 400
MINSPEED = 10

REPORTED_ERROR_MSG = "Reported error is: %s"

TERMINATED_BY_SIGNAL = _("The program was terminated by signal: %s.\n")

PROGRAM_MUST_TERMINATE_NOW = _("The program must terminate now.")


class EspeakError(Exception):
    pass


class InternalError(Exception):
    pass


def translate_control_chars(s):
    return literal_eval('u"%s"' % s.replace('"', r"\""))


PSSUSPEND = None

if WINDOWS and not PSUTIL_INSTALLED:
    for program in ["pssuspend", "pssuspend64"]:
        try:
            subprocess.run(
                [program, "-"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            PSSUSPEND = program
            break
        except Exception:
            pass


# For the time being, we will not provide a way to change this value at runtime
MAX_LEVENSHTEIN = 5
