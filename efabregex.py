#!/usr/bin/env python3

# EFABREGEX: a companion module for EFABULOR and EFABTRANS
# Copyright (C) 2021, 2022 Esteban Flamini <http://estebanflamini.com>

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

import re
import gettext
from os import environ
from sys import path

# Localisation should be easy
DOMAIN = 'efabregex'
if 'TEXTDOMAINDIR' in environ and gettext.find(DOMAIN, environ['TEXTDOMAINDIR']):
  gettext.install(DOMAIN, environ['TEXTDOMAINDIR'])
elif gettext.find(DOMAIN, path[0]):
  gettext.install(DOMAIN, path[0])
else:
  gettext.install(DOMAIN)


class error(Exception):
  pass


INVALID_FLAGS      = _('invalid flags')
WRONG_PATTERN      = _('wrong pattern')
WRONG_SUBSTITUTION = _('wrong substitution')


_valid_delimiters  = '/_:%"!@'
_default_delimiter = _valid_delimiters[0]
_valid_flag_chars  = 'ismuL0-'
_flag_dict         = {'i': re.IGNORECASE, 's': re.DOTALL, 'm': re.MULTILINE, 'u': re.UNICODE, 'L': re.LOCALE }


# Adding capturing groups might break several functions
_SUBST_REGEX                   = r's?([%s])(.+)\1(.*)\1(\S*)$' % _valid_delimiters
_SUBST_REGEX_PATTERN_GROUP     = 2
_SUBST_REGEX_REPLACEMENT_GROUP = 3
_SUBST_REGEX_FLAGS_GROUP       = 4
_PATTERN_REGEX                 = r'([%s])(.+)\1(\S*)$' % _valid_delimiters
_PATTERN_REGEX_PATTERN_GROUP   = 2
_PATTERN_REGEX_FLAGS_GROUP     = 3


def _get_match(regex, s, n):
  s = s.strip()
  m = re.match(regex, s, flags=re.UNICODE)
  if not m:
    return None
  delimiter = m.group(1)
  s = s.replace(r'\[', '')
  s = s.replace(r'\]', '')
  s = re.sub(r'\[.*?\]', '', s)
  s = s.replace('\\' + delimiter, '')
  return m if s.count(delimiter) == n else None


def _get_substitution_match(s):
  return _get_match(_SUBST_REGEX, s, 3)


def is_substitution(s):
  return _get_substitution_match(s) is not None


def _get_pattern_match(s):
  return _get_match(_PATTERN_REGEX, s, 2)


def is_pattern(s):
  return _get_pattern_match(s) is not None


def is_regex(s):
  return is_substitution(s) or is_pattern(s)


def contains_invalid_flags(s):
  m = _get_substitution_match(s) or _get_pattern_match(s)
  if not m:
    return False
  flags = m.groups()[-1]
  return _invalid_flags(flags)


def _invalid_flags(s):
  return any([x not in _valid_flag_chars for x in s]) or \
         s and s[-1] == '-' or \
         '-0' in s or \
         '--' in s or \
         any([s.count(x) > 1 for x in _valid_flag_chars])


def is_unterminated(s):
  s = s.strip()
  if not s or len(s) < 3 or is_regex(s):
    return False
  if s[0] == 's' and s[1] in _valid_delimiters:
    return True # The previous test ensures it is not a valid substitution regex
  return s[0] in _valid_delimiters and s[-1] != s[0]


def is_possibly_wrong_substitution(s):
  s = s.strip()
  return s and len(s) > 2 and not is_substitution(s) and (is_substitution(s[1:]) or is_pattern(s) and contains_invalid_flags(s))


# Compile regex flags
def _get_flags(s):
  flags = 0 if '0' in s else _default_flags
  switches = re.findall('-?[%s]' % _valid_flag_chars, s)
  for letter, flag in _flag_dict.items():
    if '-' + letter in switches:
      flags &= ~flag
    elif letter in switches:
      flags |= flag
  return flags


_default_flags = 0


def set_default_flags(s):
  global _default_flags

  if _invalid_flags(s) or '0' in s or '-' in s:
    raise error(INVALID_FLAGS)
  _default_flags = 0
  _default_flags = _get_flags(s)


def get_default_flags():
  return _default_flags


def compile(s):
  m = _get_pattern_match(s)
  if not m:
    raise error(WRONG_PATTERN)
  flags = m.group(_PATTERN_REGEX_FLAGS_GROUP)
  if _invalid_flags(flags):
    raise error(INVALID_FLAGS)
  pattern = m.group(_PATTERN_REGEX_PATTERN_GROUP)
  try:
    regex_object = re.compile(pattern, _get_flags(flags))
    return (regex_object, pattern)
  except re.error as e:
    raise error(e)


def create_match(s):
  return _default_delimiter + s + _default_delimiter


def compile_substitution(s):
  m = _get_substitution_match(s)
  if not m:
    raise error(WRONG_SUBSTITUTION)
  flags = m.group(_SUBST_REGEX_FLAGS_GROUP)
  if _invalid_flags(flags):
    raise error(INVALID_FLAGS)
  pattern = m.group(_SUBST_REGEX_PATTERN_GROUP)
  repl = m.group(_SUBST_REGEX_REPLACEMENT_GROUP)
  repl = re.sub(r'\$(\d+)', lambda x: '\\' + x.group(1), repl) # Replace \ for $ in backreferences
  try:
    regex_object = re.compile(pattern, _get_flags(flags))
    return (regex_object, pattern, repl)
  except re.error as e:
    raise error(e)


def create_substitution(s, repl):
  m = _get_match(_PATTERN_REGEX, s, 2)
  if not m:
    raise error(WRONG_PATTERN)
  pattern = m.group(_PATTERN_REGEX_PATTERN_GROUP)
  flags = m.group(_PATTERN_REGEX_FLAGS_GROUP)
  return 's' + _default_delimiter + pattern + _default_delimiter + repl + _default_delimiter + flags


if __name__ == '__main__':
  print(_('This module contains functions to be used by other modules, and is not supposed to be called directly by the user.'))

