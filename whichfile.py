#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" whichfile.py
    ...Resolves symlinks to find out where a link is pointing to.
       It lists all the links along the way, not just the end point.
       It will determine the file type like the `file` command.
    -Christopher Welborn 08-09-2014
"""

import magic
import os
import sys
from docopt import docopt
from subprocess import getoutput

NAME = 'WhichFile'
VERSION = '0.0.2-1'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)
SCRIPTDIR, SCRIPT = os.path.split(os.path.abspath(sys.argv[0]))

USAGESTR = """{versionstr}
    Usage:
        {script} -h | -v
        {script} PATH... [-D]

    Options:
        PATH          : Directory path or paths to resolve.
        -D,--debug    : Print some debugging info.
        -h,--help     : Show this help message.
        -v,--version  : Show version.
""".format(script=SCRIPT, versionstr=VERSIONSTR)


class ResolvedPath(object):

    """ Resolve a single path, following any symlinks and determining
        the file type.
    """

    def __init__(self, spath):
        # Expand the ~ (user) path, and use an absolute path when needed.
        try:
            if '~' in spath:
                spath = spath.expanduser(spath)
            if '..' in spath:
                spath = spath.abspath(spath)
            self.path = spath
        except Exception as exabs:
            errfmt = 'Init error (abspath/expanduser): {}\n{}'
            printdebug(errfmt.format(exabs, exabs))

        # Determine if this is an absolute path, or locate it in $PATH.
        self.exists = False
        self._locate()
        self.broken = self._broken()
        # Chain of symlinks that may eventually lead to the original.
        self.symlink_to = []
        # The final target in a chain of symlinks, just the original path.
        self.target = self.path
        # This is the filetype string (gathered from the `file` command.)
        self.filetype = None

        self.resolved = False
        if self.exists:
            self._resolve()

    def __repr__(self):
        """ Same as __str__() """
        return self.__str__()

    def __str__(self):
        """ Printable string representation of this resolved path. """
        if not self.exists:
            printdebug('__str__() on non-existing file.')
            return ''
        if not self.resolved:
            printdebug('__str__() on unresolved file.')
            return str(self.path)

        lines = ['{}:'.format(self.path)]
        indent = 4
        for symlink in self.symlink_to:
            linkstatus = ''
            if self._broken(symlink):
                linkstatus = '(broken)'
            elif not self._exists(symlink):
                linkstatus = '(missing)'

            indention = ' ' * indent
            lines.append('{}-> {} {}'.format(indention, symlink, linkstatus))
            indent += 4
        # Indent some more for labels.
        indent += 7

        # if len(self.symlink_to) > 1:
        #    This is actually not needed at all. The arrows ( -> ) say it all.
        #    targetlbl = '{}'.format('Target:'.rjust(indent))
        #    lines.append('\n{} {}'.format(targetlbl, self.target))
        if self.resolved:
            typelbl = '{}'.format('Type:'.rjust(indent))
            lines.append('{} {}'.format(typelbl, self.filetype))
        return '\n'.join(lines)

    def _broken(self, path=None):
        """ Determine if a path is a broken link. """
        path = path or self.path
        return os.path.islink(path) and (not os.path.exists(path))

    def _exists(self, path=None):
        """ Determine if a path exists, or is a symlink. """
        path = path or self.path
        return os.path.exists(path) or os.path.islink(path)

    def _follow_links(self, path=None):
        path = path or self.path
        try:
            symlink = os.readlink(path)
        except OSError as exreadlink:
            printdebug('_follow_links(): readlink: {}'.format(exreadlink))
        else:
            try:
                basepath = os.path.split(path)[0]
                absolutepath = os.path.abspath(os.path.join(basepath, symlink))
            except Exception as exabs:
                printdebug('_follow_links(): abspath: {}'.format(exabs))
            else:
                yield absolutepath
                yield from self._follow_links(absolutepath)

    def _get_filetype(self, path=None):
        """ Determine a file's type like the `file` command. """
        path = path or self.path
        try:
            ftype = magic.from_file(path)
        except OSError as ex:
            printdebug('_get_filetype: Magic error: {}\n{}'.format(path, ex))
            if self.broken:
                return '<broken link to: {}>'.format(path)
            return '<unknown>'
        return ftype.decode('utf-8') if ftype else '<unknown>'

    def _locate(self):
        """ If this is not an absolute path, it will try to locate it
            in one of the PATH dirs.
        """
        if self._exists():
            printdebug('_locate(\'{p}\') = {p}'.format(p=self.path))
            self.exists = True
            return self.path

        printdebug('_locate(\'{}\')...'.format(self.path))

        dirs = [s.strip() for s in os.environ.get('PATH', '').split(':')]
        for dirpath in dirs:
            trypath = os.path.join(dirpath, self.path)
            if self._exists(trypath):
                printdebug('_locate(\'{}\') = {}'.format(self.path, trypath))
                self.path = trypath
                self.exists = True
                return self.path

        printdebug('_locate(\'{}\') failed!'.format(self.path))
        self.exists = False
        return None

    def _resolve(self):
        """ Resolve this path, following symlinks, determining file type,
            and filling in attributes along the way.
        """
        printdebug('Resolving: {}'.format(self.path))
        self.symlink_to = [p for p in self._follow_links()]
        if self.symlink_to:
            self.target = self.symlink_to[-1]

        self.filetype = self._get_filetype(self.target)
        self.resolved = True


DEBUG = False


def main(argd):
    """ Main entry point, expects doctopt arg dict as argd """
    global DEBUG
    DEBUG = argd['--debug']
    printdebug('Debug mode: on')

    errfiles = []
    for path in argd['PATH']:
        resolved = ResolvedPath(path)
        if resolved.exists:
            resolvedinfo = str(resolved)
            if resolvedinfo:
                print('\n{}'.format(resolvedinfo))
        else:
            printdebug('resolved.exists = False after resolving.')
            errfiles.append(path)

    errs = len(errfiles)
    if errs:
        pathplural = 'path' if errs == 1 else 'paths'
        print('\nThere were errors resolving {} {}.'.format(errs, pathplural))
        print('    {}'.format('\n    '.join(errfiles)))
    return errs


def printdebug(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

if __name__ == '__main__':
    mainret = main(docopt(USAGESTR, version=VERSIONSTR))
    sys.exit(mainret)
