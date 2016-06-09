#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" whichfile.py
    Resolves symlinks to find out where a link is pointing to.
    It lists all the links along the way, not just the end point.
    It will determine the file type like the `file` command.
    It will tell you what package a command can be found in, if it is
    not already installed (if CommandNotFound is installed on the system).
    -Christopher Welborn 08-09-2014
"""

import inspect
import os
import posix
import re
import sys
from contextlib import suppress
from functools import cmp_to_key

# print_err and debug are used before all imports/arg-parsing.
DEBUG = ('-D' in sys.argv) or ('--debug' in sys.argv)

ALIAS_FILES = tuple(
    s for s in (
        os.path.expanduser('~/.bash_aliases'),
        os.path.expanduser('~/bash.alias.sh')
    ) if os.path.exists(s)
)
ALIAS_FILE = ALIAS_FILES[0] if ALIAS_FILES else None

# Default colors for output.
COLOR_ARGS = {
    'cmd': {'fore': 'blue', 'style': 'bright'},
    'link': {'fore': 'blue'},
    'target': {'fore': 'lightblue'},
    'type': {'fore': 'lightgreen'}
}


def debug(*args, **kwargs):
    """ Print a message only if DEBUG is truthy. """
    if not (DEBUG and args):
        return None

    # Include parent class name when given.
    parent = kwargs.get('parent', None)
    with suppress(KeyError):
        kwargs.pop('parent')

    # Go back more than once when given.
    backlevel = kwargs.get('back', 1)
    with suppress(KeyError):
        kwargs.pop('back')

    frame = inspect.currentframe()
    # Go back a number of frames (usually 1).
    while backlevel > 0:
        frame = frame.f_back
        backlevel -= 1
    fname = os.path.split(frame.f_code.co_filename)[-1]
    lineno = frame.f_lineno
    if parent:
        func = '{}.{}'.format(parent.__class__.__name__, frame.f_code.co_name)
    else:
        func = frame.f_code.co_name

    lineinfo = '{}:{} {}: '.format(
        C(fname, 'yellow'),
        C(lineno, 'blue'),
        C().join(C(func, 'magenta'), '()').ljust(20)
    )
    # Patch args to stay compatible with print().
    pargs = list(C(a, 'green').str() for a in args)
    pargs[0] = ''.join((lineinfo, pargs[0]))
    print(*pargs, **kwargs)


def print_err(*args, **kwargs):
    """ Print an error message to stderr. """
    if kwargs.get('file', None) is None:
        kwargs['file'] = sys.stderr
    print(C(kwargs.get('sep', ' ').join(args), fore='red'), **kwargs)


try:
    from colr import (
        auto_disable as colr_auto_disable,
        Colr as C
    )
    # Automatically disable colors when piping.
    colr_auto_disable()
except ImportError as eximp:
    print_err('\nError importing the colr module: {}'.format(eximp))
    if sys.version_info.major >= 3:
        print_err('You can install it with `pip install colr`')
    else:
        print_err('Colr, and this script using Python 3+.')
    sys.exit(1)

try:
    from docopt import docopt
except ImportError as eximp:
    print_err('\nError importing the docopt module: {}'.format(eximp))
    print_err('You can install it with `pip install docopt`.\n')
    sys.exit(1)
try:
    import magic
except ImportError as eximp:
    print_err('\nError importing the python-magic module: {}'.format(eximp))
    print_err('You can install it with `pip install python-magic`.\n')
    sys.exit(1)

try:
    from CommandNotFound import CommandNotFound
    # Do not give advice if we are in a situation where apt
    # or aptitude are not available (CommandNotFound LP: #394843)
    if not (os.path.exists('/usr/bin/apt') or
            os.path.exists('/usr/bin/aptitude')):
        CommandNotFound = None
        debug('Not using CommandNotFound, apt/aptitude not found.')
except ImportError:
    # We just won't use this feature. See: get_install_msg()
    CommandNotFound = None
    debug('Not using CommandNotFound, module cannot be imported.')

NAME = 'WhichFile'
VERSION = '0.3.0'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)
SCRIPTDIR, SCRIPT = os.path.split(os.path.abspath(sys.argv[0]))

USAGESTR = """{versionstr}
    Usage:
        {script} -h | -v
        {script} PATH... [-D] [-m] [-s]
        {script} PATH... -d [-D] [-s]

    Options:
        PATH          : Directory path or paths to resolve.
        -d,--dir      : Print the parent directory of the final target.
        -D,--debug    : Print some debugging info.
        -h,--help     : Show this help message.
        -m,--mime     : Show mime type instead of human readable form.
        -s,--short    : Short output, print only the target.
                        On error nothing is printed and non-zero is returned.
                        Broken symlinks will have 'dead:' prepended to them.
        -v,--version  : Show version.
""".format(script=SCRIPT, versionstr=VERSIONSTR)

DEBUG = False


def main(argd):
    """ Main entry point, expects doctopt arg dict as argd """
    global DEBUG
    DEBUG = argd['--debug']
    debug('Debug mode: on')

    errbins = []
    for path in argd['PATH']:
        resolved = ResolvedPath(path, use_mime=argd['--mime'])
        if resolved.exists:
            if argd['--dir']:
                resolved.print_dir()
            elif argd['--short']:
                resolved.print_target()
            else:
                resolved.print_all()
        else:
            errbins.append(path)

    # Check non-binary commands.
    for cmdname, cmdline in get_bash_msgs(errbins).items():
        if cmdline:
            # Found an alias.
            errbins.remove(cmdname)
            print(format_bash_cmd(
                cmdname,
                cmdline,
                dir_only=argd['--dir'],
                short_mode=argd['--short']
            ))

    # Check for installable commands.
    errs = len(errbins)
    if errbins and (not argd['--short']):
        errs = print_err_cmds(errbins)

    return errs


def format_bash_cmd(cmdname, matchline, dir_only=False, short_mode=False):
    """ Format a found bash alias/function line for printing. """
    if dir_only:
        return str(C(os.path.split(ALIAS_FILE)[0], **COLOR_ARGS['target']))
    if short_mode:
        return str(C(ALIAS_FILE, **COLOR_ARGS['target']))

    return '\n{fname}:\n    -> {cmd}\n        -> {line}'.format(
        fname=C(ALIAS_FILE, **COLOR_ARGS['cmd']),
        cmd=C(cmdname, **COLOR_ARGS['target']),
        line=C(matchline, **COLOR_ARGS['type'])
    )


def get_bash_msgs(cmdnames):
    """ Look for bash aliases/functions with this name, but only if the
        user's shell is set to bash.
        Returns a dict of cmdnames and messages about the aliases possible
        location on success,
        Returns {} if the user's shell is not set to bash, or no bash alias
        file can be found.
        All values will be None if no commands were found in the file.
    """
    if not ALIAS_FILE:
        return {}
    elif '/bash' not in os.environ.get('SHELL', ''):
        return {}
    cmdpatfmt = '({})'.format(
        '|'.join((
            '(^alias {cmd}[ ]?)',
            '(^function {cmd}\(?\)?$)',
            '(^{cmd}\(\)$)'
        ))
    ).format

    # Build a dict of {cmdname: regex_pattern} before opening the file.
    cmdpats = {}
    for cmd in cmdnames:
        try:
            cmdpat = re.compile(cmdpatfmt(cmd=cmd))
        except re.error as ex:
            print_err('Cannot search alias file for: {}\n{}'.format(
                cmd,
                ex
            ))
        else:
            cmdpats[cmd] = cmdpat
    if not cmdpats:
        # No patterns to search for, all of them errored.
        return {}
    # Set all messages to None, until proven othewise.
    cmdmsgs = {cmd: None for cmd in cmdnames}
    with open(ALIAS_FILE, 'r') as f:
        for line in f:
            l = line.strip()
            for cmdname, cmdpat in cmdpats.items():
                if cmdpat is None:
                    # Already found and added.
                    continue
                match = cmdpat.search(l)
                if match is not None:
                    # Found the command, add it's message, remove it from
                    # the list of command regex patterns, and stop searching
                    # this line for other commands.
                    cmdpats[cmdname] = None
                    cmdmsgs[cmdname] = l
                    break

    return cmdmsgs


def get_install_msg(cmdname, ignore_installed=True):
    """ Use CommandNotFound if it is installed, to find any apt
        packages that may be available.
        Returns None when no packages are found,
        and install intructions when there are packages available.
    """
    if CommandNotFound is None:
        # Feature not enabled.
        return None
    cmdname = os.path.split(cmdname)[-1]

    # Instantiate CommandNotFound, using default data dir.
    cnf = CommandNotFound()
    if cmdname in cnf.getBlacklist():
        return None

    packages = cnf.getPackages(cmdname)
    pkglen = len(packages)
    if pkglen == 0:
        return None
    if pkglen == 1:
        msgfmt = '\n'.join((
            'The program \'{cmd}\' is currently not installed.',
            '    You can install it by typing: {sudo}apt install {pkgname}'
        ))
        if posix.geteuid() == 0:
            # User is root.
            msg = msgfmt.format(
                cmd=cmdname,
                sudo='',
                pkgname=packages[0][0]
            )
        elif cnf.user_can_sudo:
            msg = msgfmt.format(
                cmd=cmdname,
                sudo='sudo ',
                pkgname=packages[0][0]
            )
        else:
            msg = ' '.join((
                'To run \'{cmd}\' please ask your administrator to install',
                'the package \'{pkg}\''
            )).format(cmd=cmdname, pkg=packages[0][0])
        if not packages[0][1] in cnf.sources_list:
            msg = '\n'.join((
                msg,
                'You will have to enable the component called \'{}\''.format(
                    packages[0][1]
                )
            ))
        return msg
    if pkglen > 1:
        # Multiple packages available.
        packages.sort(key=cmp_to_key(cnf.sortByComponent))
        msg = [
            'The program \'{cmd}\' can be found in the following packages:'
        ]
        for package in packages:
            if package[1] in cnf.sources_list:
                msg.append('    * {pkg}'.format(pkg=package[0]))
            else:
                msg.append(
                    '    * {pkg} ({extramsg} {component})'.format(
                        pkg=package[0],
                        extramsg='You will have to enable a component called',
                        component=package[1]
                    )
                )
        installmsg = '    Try {sudo}apt install <selected package>'
        if posix.geteuid() == 0:
            msg.append(installmsg)
            return '\n'.join(msg).format(cmd=cmdname, sudo='')
        elif cnf.user_can_sudo:
            msg.append(installmsg)
            return '\n'.join(msg).format(cmd=cmdname, sudo='sudo ')
        else:
            installmsg = '    Ask your administrator to install one of them.'
            msg.append(installmsg)
            return '\n'.join(msg).format(cmd=cmdname)


def print_err_cmds(errcmds):
    """ Print all files that errored, with possible install suggestions.
        Returns the number of errored files.
    """
    errs = len(errcmds)
    if not errs:
        return 0
    # Get a list of (cmd, install_instructions) where available.
    installable = ((cmd, get_install_msg(cmd)) for cmd in errcmds)
    installable = {cmd: instr for cmd, instr in installable if instr}
    installlen = len(installable)
    print_err(
        '\nThere were errors resolving {} {}, {} {} installable.'.format(
            errs,
            'path' if errs == 1 else 'paths',
            installlen,
            'is' if installlen == 1 else 'are'
        )
    )
    for cmd in errcmds:
        instr = installable.get(
            cmd,
            '\'{}\' is not a known program or file path.'.format(cmd)
        )
        print_err('\n    {}'.format(instr.replace('\n', '\n    ')))
    return errs


class ResolvedPath(object):

    """ Resolve a single path, following any symlinks and determining
        the file type.
    """

    def __init__(self, path, use_mime=False):
        """
            Arguments:
                path     (str)  : A str path to resolve.
                use_mime (bool) : Use mime type, not human readable text.

            The path/link is resolved on initialization.
            Information about the path will be in the public attributes:
                broken     : Whether this is an existing, but broken symlink.
                exists     : Whether this is an existing path.
                filetype   : File type from libmagic in human readable form,
                             or mime type if use_mime is True.
                resolved   : Whether this path is resolved yet.
                             This will be false for non-existing paths.
                symlink_to : List of link targets (in order).
                target     : Final target for this link.

        """

        self.use_mime = use_mime
        # Expand the ~ (user) path, and use an absolute path when needed.
        self.path = self._expand(path)

        # Determine if this is an absolute path, or locate it in $PATH.
        self.exists = False
        self._locate()
        self.broken = self._broken()

        self.symlink_to = []
        self.target = self.path
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
            debug('__str__() on non-existing file.')
            return ''
        if not self.resolved:
            debug('__str__() on unresolved file.')
            return str(self.path)

        lines = ['{}:'.format(C(self.path, **COLOR_ARGS['cmd']))]
        indent = 4
        lastlink = len(self.symlink_to) - 1
        for i, symlink in enumerate(self.symlink_to):
            linkstatus = ''
            if self._broken(symlink):
                linkstatus = C('(broken)', fore='red')
            elif not self._exists(symlink):
                linkstatus = C('(missing)', fore='red')
            else:
                symlink = C(
                    symlink,
                    **COLOR_ARGS['target' if i == lastlink else 'link']
                )
            indention = ' ' * indent
            lines.append('{}-> {} {}'.format(indention, symlink, linkstatus))
            indent += 4

        # Indent some more for labels.
        indent += 7
        if self.resolved:
            typelbl = 'Type:'.rjust(indent)
            lines.append(
                '{} {}'.format(
                    typelbl,
                    C(self.filetype, **COLOR_ARGS['type'])
                )
            )
        return '\n'.join(lines)

    def _broken(self, path=None):
        """ Determine if a path is a broken link. """
        path = path or self.path
        return os.path.islink(path) and (not os.path.exists(path))

    def _exists(self, path=None):
        """ Determine whether a path exists,
            or is at least an existing broken link.
        """
        # os.path.exists() returns False for existing broken links.
        path = path or self.path
        return os.path.islink(path) or os.path.exists(path)

    def _expand(self, path):
        """ Expand user paths, and use abspath when needed.
            Return the expanded path.
        """
        try:
            if '~' in path:
                path = path.expanduser(path)
            if '..' in path:
                path = path.abspath(path)
        except Exception as exabs:
            errfmt = 'Init error (abspath/expanduser): {}\n{}'
            debug(errfmt.format(exabs, exabs))

        return path

    def _follow_links(self, path=None):
        path = path or self.path
        try:
            symlink = os.readlink(path)
        except OSError as exreadlink:
            debug('_follow_links(): readlink: {}'.format(exreadlink))
        else:
            try:
                basepath = os.path.split(path)[0]
                absolutepath = os.path.abspath(
                    os.path.join(basepath, symlink)
                )
            except Exception as exabs:
                debug('_follow_links(): abspath: {}'.format(exabs))
            else:
                yield absolutepath
                for s in self._follow_links(absolutepath):
                    yield s

    def _get_filetype(self, path=None):
        """ Determine a file's type like the `file` command. """
        path = path or self.path
        try:
            ftype = magic.from_file(path, mime=self.use_mime).decode()
        except EnvironmentError as ex:
            debug('_get_filetype: Magic error: {}\n{}'.format(path, ex))
            if self.broken:
                return '<broken link to: {}>'.format(path)
            ftype = None
        if ftype is None and os.path.isdir(path):
            ftype = 'directory'

        return ftype or '<unknown>'

    def _locate(self):
        """ If this is not an absolute path, it will try to locate it
            in one of the PATH dirs.
            Sets self.path, and returns the full absolute path on success.
            Returns None for non-existing paths.
        """
        if self._exists(self.path):
            debug('_locate(\'{p}\') = {p}'.format(p=self.path))
            self.exists = True
            return self.path

        debug('_locate(\'{}\')...'.format(self.path))

        dirs = [s.strip() for s in os.environ.get('PATH', '').split(':')]
        for dirpath in dirs:
            trypath = os.path.join(dirpath, self.path)
            if self._exists(trypath):
                debug('_locate(\'{}\') = {}'.format(self.path, trypath))
                self.path = trypath
                self.exists = True
                return self.path

        debug('_locate(\'{}\') failed!'.format(self.path))
        self.exists = False
        return None

    def _resolve(self):
        """ Resolve this path, following symlinks, determining file type,
            and filling in attributes along the way.
        """
        debug('Resolving: {}'.format(self.path))
        self.symlink_to = [p for p in self._follow_links()]
        if self.symlink_to:
            self.target = self.symlink_to[-1]

        self.filetype = self._get_filetype(self.target)
        if self.filetype == 'directory':
            self.target = os.path.abspath(self.target or self.path)
        self.resolved = True

    def print_all(self):
        """ Prints str(self) if it's not an empty string. """
        info = str(self)
        if info:
            print('\n{}'.format(info))

    def print_dir(self, end='\n'):
        """ Prints the parent directory for self.target if it is set. """
        if self.target:
            pdir, _ = os.path.split(self.target)
            if pdir:
                print(C(pdir, **COLOR_ARGS['target']), end=end)

    def print_target(self, end='\n'):
        """ Prints self.target if it is set.
            Broken links will have 'dead:' prepended to them.
        """
        if self.target:
            if self.broken:
                targetstr = 'dead:{}'.format(C(self.target, fore='red'))
            else:
                targetstr = C(self.target, **COLOR_ARGS['target'])
            print(targetstr, end=end)


class InvalidArg(ValueError):
    """ Raised when the user has used an invalid argument. """
    def __init__(self, msg=None):
        self.msg = msg or ''

    def __str__(self):
        if self.msg:
            return 'Invalid argument, {}'.format(self.msg)
        return 'Invalid argument!'


if __name__ == '__main__':
    try:
        mainret = main(docopt(USAGESTR, version=VERSIONSTR))
    except InvalidArg as ex:
        print_err(ex)
        mainret = 1
    except (EOFError, KeyboardInterrupt):
        print_err('\nUser cancelled.\n', file=sys.stderr)
        mainret = 2
    except BrokenPipeError:
        print_err(
            '\nBroken pipe, input/output was interrupted.\n',
            file=sys.stderr)
        mainret = 3
    except EnvironmentError as ex:
        print_err('\n{}'.format(ex))
        mainret = 1

    sys.exit(mainret)
