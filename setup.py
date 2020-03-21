#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WhichFile Setup

-Christopher Welborn 03-21-2020
"""

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

# Try using the latest DESC.txt.
shortdesc = 'Reports symlink targets and file types, like `which` and `file`.'
try:
    with open('DESC.txt', 'r') as f:
        shortdesc = f.read()
except FileNotFoundError:
    pass

# Default README files to use for the longdesc, if pypandoc fails.
readmefiles = ('docs/README.txt', 'README.txt', 'docs/README.rst')
for readmefile in readmefiles:
    try:
        with open(readmefile, 'r') as f:
            longdesc = f.read()
        break
    except EnvironmentError:
        # File not found or failed to read.
        pass
else:
    # No readme file found.
    # If a README.md exists, and pypandoc is installed, generate a new readme.
    try:
        import pypandoc
    except ImportError:
        print('Pypandoc not installed, using default description.')
        longdesc = shortdesc
    else:
        # Convert using pypandoc.
        try:
            longdesc = pypandoc.convert('README.md', 'rst')
        except EnvironmentError:
            # No readme file, no fresh conversion.
            print('Pypandoc readme conversion failed, using default desc.')
            longdesc = shortdesc

setup(
    name='WhichFile',
    version='1.0.3',
    author='Christopher Welborn',
    author_email='cjwelborn@live.com',
    packages=['whichfile'],
    url='https://github.com/welbornprod/whichfile',
    description=shortdesc,
    long_description=longdesc,
    keywords=('python python3 2 3 which file whichfile tool executable'),
    classifiers=[
        ' :: '.join((
            'License',
            'OSI Approved',
            'GNU General Public License v2 or later (GPLv2+)',
        )),
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3 :: Only'
    ],
    install_requires=[
        'colr>=0.9.1',
        'docopt>=0.6.2',
        'findfunc>=0.4.5',
        'formatblock>=0.3.6',
        'python-magic>=0.4.15',
    ],
    entry_points={
        'console_scripts': [
            'whichfile = whichfile.__main__:entry_point',
        ],
    },
)
