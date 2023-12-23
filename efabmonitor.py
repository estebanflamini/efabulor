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

import efablogger
from efabcore import terminate, start_daemon


_MONITORING_ERROR = _(
    "Error while trying to get modification time of file/directory: %s"
)
_WRONG_MONITORED_TARGET = _(
    "%s is not a file nor a directory. Its modification time cannot be "
    "checked."
)
_CHECKING = _("Checking modification times of monitored files/directories.")
_NO_MODIFICATIONS = _("No modification time changes were detected.")
_TIMESTAMP_CHANGED = _("Modification time changed: %s (%s).")


def _format(mtime):
    return time.strftime("%X", time.localtime(mtime))


class FileMonitor:

    def __init__(self, options):
        self._files = []
        self._actions = {}
        self._modification_times = {}
        self._options = options
        self._lock = threading.RLock()

    def register(self, group, action):
        with self._lock:
            self._files.extend(group)
            self._actions[tuple(group)] = action
            self._initialize(group)

    def _initialize(self, files):
        with self._lock:
            for fn in files:
                try:
                    self._modification_times[fn] = os.path.getmtime(fn)
                except IOError as e:
                    with efablogger.lock:
                        efablogger.say(
                            _MONITORING_ERROR % fn,
                            type_of_msg=efablogger.ERROR
                        )
                        terminate(REPORTED_ERROR_MSG % e)

    def run(self):
        with self._lock:
            interval = self._options.monitoring_interval
        while True:
            n = 0
            while n < interval:
                time.sleep(1)
                n += 1
                with self._lock:
                    interval = self._options.monitoring_interval
            self.check_files(say_it=False, called_from_monitoring_thread=True)

    def check_files(self, say_it=True, called_from_monitoring_thread=False):
        if not called_from_monitoring_thread:
            # The method was called from efabcmd in the main thread
            start_daemon(
                lambda: self.check_files(called_from_monitoring_thread=True)
            )
            return True
        with self._lock:
            files_to_check = list(self._actions.items())
        changed_files = False
        if say_it:
            self._log_checking()
        for group, action in files_to_check:
            for f in group:
                if self._check_file(f):
                    changed_files = True
                    action(f)
        if changed_files:
            return True
        elif say_it:
            efablogger.say(_NO_MODIFICATIONS, type_of_msg=efablogger.INFO)
            return False

    def _log_checking(self):
        efablogger.say(_CHECKING, type_of_msg=efablogger.INFO)

    def _check_file(self, f):
        if os.path.isfile(f) or os.path.isdir(f):
            try:
                mtime = os.path.getmtime(f)
                if mtime != self._modification_times[f]:
                    self._modification_times[f] = mtime
                    self._log_modified(f, mtime)
                    return True
            except IOError as e:
                with efablogger.lock:
                    efablogger.say(
                        _MONITORING_ERROR % f,
                        type_of_msg=efablogger.ERROR
                    )
                    efablogger.report_error(e)
                    terminate(PROGRAM_MUST_TERMINATE_NOW)
        else:
            efablogger.say(
                _WRONG_MONITORED_TARGET % f,
                type_of_msg=efablogger.ERROR
            )
        return False

    def _log_modified(self, f, mtime):
        efablogger.say(
            _TIMESTAMP_CHANGED % (f, _format(mtime)),
            type_of_msg=efablogger.INFO
        )
