#!/usr/bin/env python3

# EFABCONV: a command-line wrapper for printing different types of files to standard output
# Copyright (C) 2021 Esteban Flamini <http://estebanflamini.com>

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

__version__ = '0.99'

import os
import sys
import argparse
import subprocess
import re
import locale
import gettext
import shlex
import traceback
import platform

DEFAULT_CONFIG_FILE = sys.path[0] + '/efabconv.cfg'

# Localisation should be easy
DOMAIN = 'efabconv'
if 'TEXTDOMAINDIR' in os.environ and gettext.find(DOMAIN, os.environ['TEXTDOMAINDIR']):
  gettext.install(DOMAIN, os.environ['TEXTDOMAINDIR'])
elif gettext.find(DOMAIN, sys.path[0]):
  gettext.install(DOMAIN, sys.path[0])
else:
  gettext.install(DOMAIN)

lang = None

args = None
conv = None

PLATFORM = platform.system()

UNSUPPORTED_PLATFORM = _('Unsupported operation for platform: %s.') % PLATFORM

def get_default_conversion_rules_file():
  if os.path.isfile(DEFAULT_CONFIG_FILE):
    return DEFAULT_CONFIG_FILE
  return None


def main():
  global args
  global conv
  global lang
  
  parser = argparse.ArgumentParser(prog='efabconv.py')
  parser.add_argument('-c', '--config-file', metavar=_('<configuration file>'), default=get_default_conversion_rules_file())
  parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)
  parser.add_argument('infile', nargs='+', metavar=_('<file to read input from>'))
  parser.add_argument('--lang', default=None, metavar=_('<language ISO code>'))
  args = parser.parse_args()

  lang = args.lang or locale.getdefaultlocale()[0].split('_')[0]

  if args.config_file:
    if not os.path.exists(args.config_file):
      sys.exit(_('File %s does not exist.') % args.config_file)
    if not os.path.isfile(args.config_file):
      sys.exit(_('%s is not a file.') % args.config_file)
    try:
      with open(args.config_file, 'r') as f:
        conv = f.read()
    except IOError:
      sys.exit(_('Cannot read configuration file: %s.') % args.config_file)
  else:
    conv = None

  for f in args.infile:
    if not os.path.isfile(f):
      sys.exit(_('File %s does not exist.') % f)
    else:
      process(f)
  

MIME_CONVERSION_RULE = r'(?m)^mime:\s+%s\s*?^do:\s+(.+?)$'
EXT_CONVERSION_RULE = r'(?m)^ext:\s+%s\s*^do:\s+(.+?)$'


# If you modify this function, be VERY careful to sanitize cmd, as it will be executed thru a shell in run()
def process(f):
  mt = mimetype(f)
  m = re.search(MIME_CONVERSION_RULE % mt, conv) if conv and mt else None
  if m:
    conversion_rule = m.group(1)
  elif mt == 'text/plain':
    if PLATFORM == 'Linux':
      conversion_rule = 'cat $file'
    elif PLATFORM == 'Windows':
      conversion_rule = 'cmd /C type $file'
    else:
      traceback.print_stack()
      sys.exit(UNSUPPORTED_PLATFORM)
  elif not conv:
    sys.exit(_('Mimetype of %s is not text/plain and no configuration file for conversion was provided.') % f)
  else:
    ext = os.path.splitext(f)[1]
    if ext:
      m = re.search(EXT_CONVERSION_RULE % ext[1:], conv)
      if m:
        conversion_rule = m.group(1)
      else:
        sys.exit(_('No action configured for extension %s in config file: %s') % (ext[1:], args.config_file))
    else:
      sys.exit(_('No action configured for mimetype: %s') % mt)
  input_command = conversion_rule.replace('$lang', shlex.quote(lang))
  input_command = input_command.replace('$file', shlex.quote(f))
  run(input_command, conversion_rule)


def mimetype(f):
  if PLATFORM == 'Linux':
    try:
      # TODO: portability issue
      mt = subprocess.check_output(['mimetype', '-b', f], text=True, stderr=subprocess.STDOUT).strip()
      return mt
    except Exception as e:
      if isinstance(e, subprocess.CalledProcessError):
        print(e.output.strip(), file=sys.stderr)
      sys.exit(_('Cannot determine mimetype of file: %s. Reported error is: %s') % (f, e))
  elif PLATFORM == 'Windows':
    return 'text/plain' if f.lower().endswith('.txt') else None
  else:
    traceback.print_stack()
    sys.exit(UNSUPPORTED_PLATFORM)


def run(input_command, conversion_rule):
  # input_command is already sanitized
  input_pipeline = create_input_pipeline(input_command, conversion_rule)
  result = None
  try:
    for cmd in input_pipeline:
      result = subprocess.run(cmd, input=result, check=True, capture_output=True).stdout
    sys.stdout.buffer.write(result)
  except Exception as e:
    if isinstance(e, subprocess.CalledProcessError):
      sys.stderr.buffer.write(e.stderr.strip())
    print(_('Conversion failed. Reported error is: %s') % e, file=sys.stderr)
    sys.exit(1)


def create_input_pipeline(cmd, conversion_rule):
  try:
    return _create_input_pipeline(shlex.split(cmd))
  except ValueError as e:
    print(_('A wrong conversion command was tried as the result of a conversion rule:\n\n%s\n') % cmd, file=sys.stderr)
    print(_('Reported error is: %s.\n') % e, file=sys.stderr)
    sys.exit(_('The rule which was set in configuration file %s is:\n\n%s\n') % (args.config_file, conversion_rule))


def _create_input_pipeline(cmd):
  if '|' in cmd:
    n = cmd.index('|')
    return [cmd[0:n]] + _create_input_pipeline(cmd[n+1:])
  return [cmd]


if __name__ == '__main__':
  main()
else:
  print(_('This module is not for import.'), file=sys.stderr)
  sys.modules[__name__] = None
