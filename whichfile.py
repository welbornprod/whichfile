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

import os
import posix
import re
import subprocess
import sys
from contextlib import suppress
from functools import cmp_to_key

NAME = 'WhichFile'
VERSION = '0.6.1'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)
SCRIPTDIR, SCRIPT = os.path.split(os.path.abspath(sys.argv[0]))

USAGESTR = """{versionstr}

    Reveals the actual location and file type for a given path or command.
    Also handles BASH builtins, aliases, and functions.

    Usage:
        {script} -h | -p | -v
        {script} PATH... [-b | -B] [-c] [-D] [-N] [-s]
        {script} PATH... [-d | -m] [-c] [-D] [-N] [-s]

    Options:
        PATH             : Directory path or paths to resolve.
        -b,--builtins    : Only show builtins when another binary exists.
        -B,--nobuiltins  : Don't check BASH builtins.
        -c,--ignorecwd   : Ignore files in the CWD, and try $PATH instead.
        -d,--dir         : Print the parent directory of the final target.
                           This enables --nobuiltins.
        -D,--debug       : Print some debugging info.
        -h,--help        : Show this help message.
        -m,--mime        : Show mime type instead of human readable form.
                           This enables --nobuiltins.
        -N,--debugname   : Shows bash alias/function lines that don't match
                           a function/alias pattern, but were found in the
                           line. This is for debugging `{script}` itself.
        -p,--path        : List directories in $PATH, like:
                           echo "$PATH" | tr ':' '\\n'
        -s,--short       : Short output, print only the target.
                           On error nothing is printed and non-zero is
                           returned.
                           Broken symlinks will be prepended with 'dead:'.
        -v,--version     : Show version.
""".format(script=SCRIPT, versionstr=VERSIONSTR)

# debug is used before arg-parsing.
DEBUG = ('-D' in sys.argv) or ('--debug' in sys.argv)

ALIAS_FILES = tuple(
    s for s in (
        os.path.expanduser('~/.bash_aliases'),
        os.path.expanduser('~/bash.alias.sh'),
        '/etc/.bash_aliases',
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

# User's PATH as a list.
PATH = [
    s.strip() for s in
    os.environ.get('PATH', '').split(':')
]


def import_err(name, ex):
    """ Print a helpful msg when third-party imports fail. """
    print(
        '\n'.join((
            'Missing third-party library: {name}',
            'You can install it with pip: `pip install {module}`',
            'Original error was: {ex}',
        )).format(name=name, module=name.lower(), ex=ex),
        file=sys.stderr
    )
    sys.exit(1)


try:
    from colr import (
        auto_disable as colr_auto_disable,
        Colr as C,
        disabled as colr_disabled,
    )
    # Automatically disable colors when piping.
    colr_auto_disable()
except ImportError as eximp:
    import_err('Colr', eximp)

try:
    from colr import docopt
except ImportError as eximp:
    import_err('Docopt', eximp)

try:
    import magic
except ImportError as eximp:
    import_err('Python-Magic', eximp)

try:
    from printdebug import DebugColrPrinter
    debugprinter = DebugColrPrinter()
    if not DEBUG:
        debugprinter.disable()
    debug = debugprinter.debug
except ImportError as eximp:
    import_err('PrintDebug', eximp)

try:
    from CommandNotFound import CommandNotFound
    # Do not give advice if we are in a situation where apt
    # or aptitude are not available (CommandNotFound LP: #394843)
    if not (os.path.exists('/usr/bin/apt') or
            os.path.exists('/usr/bin/aptitude')):
        CommandNotFound = CNF = None  # noqa
        debug('Not using CommandNotFound, apt/aptitude not found.')
    else:
        # Instantiate CommandNotFound, using default data dir.
        CNF = CommandNotFound()
except ImportError:
    # We just won't use this feature. See: get_install_msg()
    CommandNotFound = CNF = None
    debug('Not using CommandNotFound, module cannot be imported.')


# ----------------------------- Main entry point -----------------------------
def main(argd):
    """ Main entry point, expects doctopt arg dict as argd """
    debug('Debug mode: on')

    # Quick PATH list and exit.
    if argd['--path']:
        paths = ResolvedPath.get_env_path()
        print('\n'.join(paths))
        return 0 if paths else 1

    no_builtins = argd['--nobuiltins'] or argd['--dir'] or argd['--mime']
    possible_exes = argd['PATH'] if no_builtins else []
    known_builtins = []
    # Builtins have no directory, so --dir and --nobuiltins cancels this.
    if not no_builtins:
        # Check BASH builtins.
        for cmdname in argd['PATH']:
            bashmsg = get_bash_type(cmdname, short=False)
            if not str_contains(bashmsg, ('alias', 'function', 'shell')):
                possible_exes.append(cmdname)
                continue
            known_builtins.append(cmdname)
            if not argd['--builtins']:
                possible_exes.append(cmdname)
            builtinhelp = get_bash_builtin_help(cmdname)
            print(format_bash_builtin(
                cmdname,
                bashmsg,
                helpmsg=builtinhelp,
                short_mode=argd['--short']
            ))
    if no_builtins:
        debug('Skipped builtins.')
    else:
        debug('Known builtins: {} -> {!r}'.format(
            len(known_builtins),
            known_builtins
        ))
    # Resolve all arguments.
    errbins = []
    for path in possible_exes:
        resolved = ResolvedPath(
            path,
            use_mime=argd['--mime'],
            ignore_cwd=argd['--ignorecwd']
        )
        if resolved.exists:
            if argd['--dir']:
                resolved.print_dir()
            elif argd['--short']:
                resolved.print_target()
            else:
                resolved.print_all()
        else:
            errbins.append(path)

    debug('Non exes: {} -> {!r}'.format(len(errbins), errbins))
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

    # If we found builtins earlier (and --builtins was not used), don't
    # show them as an error.
    for builtincmd in known_builtins:
        try:
            errbins.remove(builtincmd)
        except ValueError:
            # Happens when only the builtin was found, no exe.
            pass

    # Check for installable commands.
    errs = len(errbins)
    debug('Errors: {} -> {!r}'.format(errs, errbins))
    if errbins and (not argd['--short']):
        errs = print_err_cmds(errbins, ignore_cwd=argd['--ignorecwd'])
    return errs


def format_bash_builtin(cmdname, msg, helpmsg=None, short_mode=False):
    """ Format a found bash builtin for printing. """
    if short_mode:
        return str(C(msg, **COLOR_ARGS['target']))

    if helpmsg:
        return '\n{cmdname}:\n    ⯈ {msg}\n        Desc.: {helpmsg}'.format(
            cmdname=C(cmdname, **COLOR_ARGS['cmd']),
            msg=C(msg.replace('shell', 'BASH'), **COLOR_ARGS['target']),
            helpmsg=C(helpmsg, **COLOR_ARGS['type'])
        )

    return '\n{cmdname}:\n    ⯈ {msg}'.format(
        cmdname=C(cmdname, **COLOR_ARGS['cmd']),
        msg=C(msg.replace('shell', 'BASH'), **COLOR_ARGS['type']),
    )


def format_bash_cmd(cmdname, matchline, dir_only=False, short_mode=False):
    """ Format a found bash alias/function line for printing. """
    if dir_only:
        return str(C(os.path.split(ALIAS_FILE)[0], **COLOR_ARGS['target']))
    if short_mode:
        return str(C(ALIAS_FILE, **COLOR_ARGS['target']))

    return '\n{fname}:\n    ⯈ {cmd}\n        ⯈ {line}'.format(
        fname=C(ALIAS_FILE, **COLOR_ARGS['cmd']),
        cmd=C(cmdname, **COLOR_ARGS['target']),
        line=C(matchline, **COLOR_ARGS['type'])
    )


def get_bash_builtin_help(name):
    """ Retrieve the first line of help for a bash builtin, using
        help `name`.
        Returns '' on error.
    """
    helpcmd = ['bash', '-c', 'help {}'.format(name)]
    try:
        rawoutput = subprocess.check_output(helpcmd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        return ''
    lines = rawoutput.decode().split('\n')
    return lines[1].strip()


def get_bash_msgs(cmdnames, debug_name=False):
    """ Look for bash aliases/functions/builtins with this name, but only if
        the user's shell is set to bash.
        Returns a dict of cmdnames and messages about the aliases possible
        location on success,
        Returns {} if the user's shell is not set to bash, or no bash alias
        file can be found.
        All values will be None if no commands were found in the file.
    """
    if not ALIAS_FILE:
        debug('No alias file to work with, cancelling.')
        return {}
    elif '/bash' not in os.environ.get('SHELL', ''):
        debug('Not a BASH environment, cancelling.')
        return {}
    bashfuncfmt = r'(^function {cmd}\(?\)? ?{{?$)'
    cmdpatfmt = '({})'.format(
        '|'.join((
            '(^alias {cmd}[ ]?)',
            bashfuncfmt,
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
        for i, line in enumerate(f):
            lineno = i + 1
            l = line.strip()
            for cmdname, cmdpat in cmdpats.items():
                if cmdpat is None:
                    # Already found and added.
                    continue
                match = cmdpat.search(l)
                if match is None:
                    if debug_name and (cmdname in l):
                        debug('Missed {!r} for {!r} in {!r}'.format(
                            debug_name,
                            cmdname,
                            l,
                        ))
                    continue
                debug('Found alias/function: {}'.format(cmdname))
                # Found the command, add it's message, remove it from
                # the list of command regex patterns, and stop searching
                # this line for other commands.
                cmdpats[cmdname] = None
                cmdfuncpat = re.compile(bashfuncfmt.format(cmd=cmdname))
                if l.startswith('alias'):
                    # The message for this alias is it's first line.
                    cmdmsgs[cmdname] = 'line {}: {}'.format(
                        lineno,
                        l
                    )
                elif cmdfuncpat.search(l):
                    # The message for this function is the output of
                    # findfunc if available.
                    funcdefstr = run_find_func(cmdname, ALIAS_FILE)
                    if funcdefstr is None:
                        # No findfunc available.
                        cmdmsgs[cmdname] = 'line {}: {}'.format(
                            lineno,
                            l
                        )
                    else:
                        cmdmsgs[cmdname] = 'line {}:\n{}'.format(
                            lineno,
                            funcdefstr
                        )
                else:
                    raise ValueError('Non alias/function found: {}'.format(l))
                break

    return cmdmsgs


def get_bash_type(name, short=True):
    """ Run `type name` in a BASH shell. Returns the decoded output.
        if `short` is truthy it returns one of:
            'alias', 'keyword', 'function', 'builtin', 'file'.
        Always returns '' on error.
    """
    typeargs = 'type -t' if short else 'type'
    typecmd = [
        'bash',
        '-c',
        '{} {}'.format(typeargs, name)
    ]
    try:
        rawoutput = subprocess.check_output(typecmd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as ex:
        debug('Failed to get bash type for: {}\n{}'.format(name, ex))
        return ''
    output = rawoutput.decode().strip()
    if output:
        debug('bash -t {}: {}'.format(name, output))
    return output


def get_cmd_location(cmdname):
    """ Find the actual path to an executable using `which` or `command -v`.
        Returns None if it cannot be found.
    """
    prev_result = get_cmd_location.results.get(cmdname, None)
    if prev_result is not None:
        debug('Using saved executable for {}: {}'.format(
            cmdname,
            prev_result
        ))
        return prev_result

    for trydir in PATH:
        fullpath = os.path.join(trydir, cmdname)
        if os.path.exists(fullpath):
            get_cmd_location.results[cmdname] = fullpath
            return fullpath
    return None


# This function remembers it's results from previous calls.
get_cmd_location.results = {}


def get_install_msg(cmdname, ignore_installed=True):
    """ Use CommandNotFound if it is installed, to find any apt
        packages that may be available.
        Returns None when no packages are found,
        and install intructions when there are packages available.
    """
    if CNF is None:
        # Feature not enabled.
        return None
    cmdname = os.path.split(cmdname)[-1]

    if cmdname in CNF.getBlacklist():
        return None

    packages = CNF.getPackages(cmdname)
    pkglen = len(packages)
    colr_args = {
        'cmd': {'fore': 'blue'},
        'installcmd': {'fore': 'green'},
        'pkg': {'fore': 'green'},
        'component': {'fore': 'yellow'},
    }
    if pkglen == 0:
        return None
    if pkglen == 1:
        msgfmt = '\n'.join((
            'The program \'{cmd}\' is currently not installed.',
            '    You can install it by typing: {installcmd}'
        ))
        if posix.geteuid() == 0:
            # User is root.
            msg = msgfmt.format(
                cmd=C(cmdname, **colr_args['cmd']),
                installcmd=C(
                    'apt install {}'.format(packages[0][0]),
                    **colr_args['installcmd']
                )
            )
        elif CNF.user_can_sudo:
            msg = msgfmt.format(
                cmd=C(cmdname, **colr_args['cmd']),
                installcmd=C(
                    'sudo apt install {}'.format(packages[0][0]),
                    **colr_args['installcmd']
                )
            )
        else:
            msg = ' '.join((
                'To run \'{cmd}\' please ask your administrator to install',
                'the package \'{pkg}\''
            )).format(
                cmd=C(cmdname, **colr_args['cmd']),
                pkg=C(packages[0][0], **colr_args['pkg'])
            )
        if not packages[0][1] in CNF.sources_list:
            msg = '\n'.join((
                msg,
                'You will have to enable the component called \'{}\''.format(
                    C(packages[0][1], **colr_args['component'])
                )
            ))
        return msg

    if pkglen > 1:
        # Multiple packages available.
        packages.sort(key=cmp_to_key(CNF.sortByComponent))
        msg = [
            'The program \'{cmd}\' can be found in the following packages:'
        ]
        for package in packages:
            if package[1] in CNF.sources_list:
                msg.append('    * {pkg}'.format(
                    pkg=C(package[0], **colr_args['pkg'])
                ))
            else:
                msg.append(
                    '    * {pkg} ({extramsg} {component})'.format(
                        pkg=C(package[0], **colr_args['pkg']),
                        extramsg='You will have to enable a component called',
                        component=C(package[1], **colr_args['component'])
                    )
                )
        installmsg = '    Try {{sudo}}{}'.format(
            C('apt install <selected package>', **colr_args['installcmd'])
        )
        if posix.geteuid() == 0:
            msg.append(installmsg)
            return '\n'.join(msg).format(
                cmd=cmdname,
                sudo=''
            )
        elif CNF.user_can_sudo:
            msg.append(installmsg)
            return '\n'.join(msg).format(
                cmd=cmdname,
                sudo=C('sudo ', **colr_args['installcmd'])
            )
        # Multiple packages, user cannot sudo.
        msg.append(C(
            '    Ask your administrator to install one of them.',
            **colr_args['installcmd']
        ))

        return '\n'.join(msg).format(cmd=C(cmdname, **colr_args['cmd']))


def print_err(*args, **kwargs):
    """ Print an error message to stderr. """

    if kwargs.get('file', None) is None:
        kwargs['file'] = sys.stderr
    nocolor = kwargs.get('nocolor', False)
    with suppress(KeyError):
        kwargs.pop('nocolor')
    if nocolor:
        print(*args, **kwargs)
    else:
        print(C(kwargs.get('sep', ' ').join(args), fore='red'), **kwargs)


def print_err_cmds(errcmds, ignore_cwd=False):
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
        '\nThere {} resolving {} {}, {} {} installable.'.format(
            'was an error' if errs == 1 else 'were errors',
            C(str(errs), fore='red', style='bright'),
            'path' if errs == 1 else 'paths',
            C(str(installlen), fore='green', style='bright'),
            'is' if installlen == 1 else 'are',
        ),
        nocolor=True
    )

    for cmd in errcmds:
        instr = installable.get(cmd, None)
        if instr is None:
            instr = '\'{}\' is not a known program or file path.'.format(
                C(cmd, fore='red')
            )
            if ignore_cwd:
                if os.path.exists(cmd):
                    instr = '\n'.join((
                        instr,
                        'It is an existing file, but was ignored.',
                    ))
                elif os.path.islink(cmd):
                    instr = '\n'.join((
                        instr,
                        'It is an existing symlink, but was ignored.',
                    ))

        print_err(
            '\n    {}'.format(instr.replace('\n', '\n    ')),
            nocolor=True
        )

    return errs


def run_find_func(cmdname, filename):
    """ Run the external `findfunc` command, if available.
        Returns the output of findfunc on success, None on error.
    """
    if run_find_func.disabled:
        # Already tried and failed to get the findfunc exe.
        return None
    if run_find_func.exepath is None:
        findfuncexe = get_cmd_location('findfunc')
        if findfuncexe is None:
            debug('`findfunc` is not available.')
            run_find_func.disabled = True
            return None
        run_find_func.exepath = findfuncexe
        debug('Using `findfunc`: {}'.format(findfuncexe))
    findcmd = [run_find_func.exepath, '--short']
    if not colr_disabled():
        # Force findfunc to use color output.
        findcmd.append('--color')
    findcmd.extend((cmdname, filename))
    output = None
    try:
        rawoutput = subprocess.check_output(findcmd)
    except subprocess.CalledProcessError as ex:
        debug('`findfunc {} {}` failed: {}'.format(cmdname, filename, ex))
        return None
    else:
        output = rawoutput.decode().strip()
    debug('Got `findfunc` output for {}'.format(cmdname))
    return output


# This function remembers it's first valid findfunc exe path.
run_find_func.exepath = None
# And whether it failed the first time.
run_find_func.disabled = False


def str_contains(s, needles):
    """ Run `in` test for several strings.
        Returns True of s contains any of the strings in `needles`.
    """
    if not s:
        return False
    for needle in needles:
        if needle in s:
            return True
    return False


class CircularLink(EnvironmentError):
    """ Raised when ResolvedPath finds a circular symlink. """
    def __init__(self, startpath, errorpath):
        self.path = startpath
        self.errorpath = errorpath
        self.start = None
        self.chain = self._find_link_chain()

    def __str__(self):
        if self.chain:
            return 'Circular link: {s.path}, at: {s.start}\n{chain}'.format(
                s=self,
                chain='\n'.join(
                    '{}{}{}'.format(
                        ' ' * i,
                        name,
                        ' ⭠' if name == self.start else ''
                    )
                    for i, name in enumerate(self.chain)
                )
            )
        return 'Circular link: {s.path}'.format(s=self)

    def _find_link_chain(self):
        realpath = os.path.abspath(self.path)
        firstdir = os.path.split(realpath)[0]
        links = [realpath]
        while True:
            path = links[-1]
            linkdir, linkname = os.path.split(path)
            if not linkdir:
                linkdir = firstdir
            link = os.path.join(linkdir, linkname)
            try:
                symlink = os.path.abspath(os.readlink(link))
            except OSError as ex:
                debug('Failed to find symlink for: {}\n{}'.format(
                    link,
                    ex
                ))
                break
            else:
                if symlink in links:
                    self.start = symlink
                    links.append(self.start)
                    break
                links.append(symlink)
        return links


class ResolvedPath(object):

    """ Resolve a single path, following any symlinks and determining
        the file type.
    """

    def __init__(self, path, use_mime=False, ignore_cwd=False):
        """
            Arguments:
                path     (str)      : A str path to resolve.
                use_mime (bool)     : Use mime type, not human readable text.
                ignore_local (bool) : Ignore paths in the CWD, and search
                                      anyway.

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

        # Set to starting path of a circular symlink  if `_follow_links()` or
        # `_get_filetype()` finds a circular symlink.
        self.circular = None
        # Determine if this is an absolute path, or locate it in $PATH.
        self.exists = False
        self._locate(ignore_cwd=ignore_cwd)
        self.broken = self._broken()

        self.symlink_to = []
        # Assume an canonical path was passed, until proven otherwise.
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
        linklen = len(self.symlink_to)
        lastlink = linklen - 1
        for i, symlink in enumerate(self.symlink_to):
            linkstatus = ''
            if self.circular:
                if symlink == self.circular:
                    linkstatus = C('⭠', 'red', style='bright')
                else:
                    linkstatus = ''
            elif self._broken(symlink):
                linkstatus = C('(broken)', fore='red')
            elif not self._exists(symlink):
                linkstatus = C('(missing)', fore='red')
            else:
                symlink = C(
                    symlink,
                    **COLOR_ARGS['target' if i == lastlink else 'link']
                )
            indention = ' ' * indent
            lines.append('{}⯈ {} {}'.format(indention, symlink, linkstatus))
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
            basepath = os.path.split(path)[0]
            absolutepath = os.path.join(basepath, symlink)
            try:
                absolutepath = os.path.abspath(absolutepath)
            except RecursionError:
                # Circular link.
                # The "circle" can start anywhere in a symlink chain,
                # so I'm using a RecursionError to detect it right now.
                exc = CircularLink(self.path, path)
                self.circular = exc.start
                debug(exc)
                raise exc
            except Exception as exabs:
                debug('_follow_links({}): abspath: {}'.format(path, exabs))
            else:
                yield absolutepath
                yield from self._follow_links(absolutepath)

    def _get_filetype(self, path=None):
        """ Determine a file's type like the `file` command. """
        path = path or self.path
        try:
            ftype = magic.from_file(path, mime=self.use_mime)
        except EnvironmentError as ex:
            if ex.errno == 40:
                # Circular symlink, this should already be caught in
                # _follow_links, which is called before this in _resolve.
                debug('_get_filetype: Magic error: {}\n{}'.format(path, ex))
                exc = CircularLink(self.path, path)
                self.circular = exc.start
            debug('_get_filetype: Magic error: {}\n{}'.format(path, ex))
            if self.broken:
                return '<broken link to: {}>'.format(path)
            ftype = None
        if ftype is None and os.path.isdir(path):
            ftype = 'directory'

        return ftype or '<unknown>'

    def _locate(self, ignore_cwd=False):
        """ If this is not an absolute path, it will try to locate it
            in one of the PATH dirs.
            Sets self.path, and returns the full absolute path on success.
            Returns None for non-existing paths.
        """
        if self._exists(self.path):
            debug('_locate(\'{p}\') = {p}'.format(p=self.path))
            if not ignore_cwd:
                self.exists = True
                return self.path
            debug('_locate(\'{p}\'): Ignoring CWD...'.format(p=self.path))

        debug('_locate(\'{}\'): Not in CWD...'.format(self.path))

        dirs = self.get_env_path()
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
        try:
            self.symlink_to = [p for p in self._follow_links()]
        except CircularLink as ex:
            self.symlink_to = ex.chain[1:]
            symlink_len = len(self.symlink_to)
            self.filetype = '<circular link: {} {} deep>'.format(
                symlink_len,
                'level' if symlink_len == 1 else 'levels',
            )
            self.target = self.path
        else:
            if self.symlink_to:
                self.target = self.symlink_to[-1]
            self.filetype = self._get_filetype(self.target)
            try:
                # For old libmagic versions, the info will not be as good.
                self.filetype = self.filetype.decode()
            except AttributeError:
                pass
        if self.filetype == 'directory':
            self.target = os.path.abspath(self.target or self.path)
        self.resolved = True

    @classmethod
    def get_env_path(cls):
        """ Return a tuple of dirs in $PATH. """
        return tuple(
            path for path in
            (s.strip() for s in os.environ.get('PATH', '').split(':'))
            if path
        )

    def print_all(self):
        """ Prints str(self) if it's not an empty string. """
        info = str(self)
        if info:
            print('\n{}'.format(info))

    def print_dir(self, end='\n'):
        """ Prints the parent directory for self.target if it is set. """
        if self.target:
            pdir, _ = os.path.split(self.target)
            if not pdir:
                pdir = os.path.abspath(pdir)
            print(C(pdir, **COLOR_ARGS['target']), end=end)

    def print_target(self, end='\n'):
        """ Prints self.target if it is set.
            Broken links will have 'dead:' prepended to them,
            circular links will have 'circular' prepended to them.
        """
        if self.target:
            if self.broken:
                msg = 'circular' if self.circular else 'dead'
                targetstr = '{}:{}'.format(msg, C(self.target, fore='red'))
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
        mainret = main(docopt(USAGESTR, version=VERSIONSTR, script=SCRIPT))
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
