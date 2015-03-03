WhichFile
=========

This is a combination of the `which` and `file` commands.
It will follow symlinks, reporting each link on the way, and then use
`libmagic` to tell you what type of file it is.


Example:
--------

Determine where `rlogin` is linked, and what type of file it is:
```
whichfile /etc/alternatives/rlogin
```

Output:
```
/etc/alternatives/rlogin:
    -> /usr/bin/slogin
        -> /usr/bin/ssh
              Type: ELF 64-bit LSB  shared object, x86-64, version 1 (SYSV), dynamically linked (uses shared libs), for GNU/Linux 2.6.24, BuildID[sha1]=2d691144f816b05319ba27679df4b847107b99d7, stripped
```

Options:
--------

```
    Usage:
        whichfile -h | -v
        whichfile PATH... [-D] [-m] [-s]

    Options:
        PATH          : Directory path or paths to resolve.
        -D,--debug    : Print some debugging info.
        -h,--help     : Show this help message.
        -m,--mime     : Show mime type instead of human readable form.
        -s,--short    : Short output, print only the final target.
                        On error nothing is printed and non-zero is returned.
        -v,--version  : Show version.
```
