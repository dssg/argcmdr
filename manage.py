"""argcmdr's own management module"""
import configparser
import copy
import re

from argcmdr import Local


class Manage(Local):
    """manage development of argcmdr ... (with argcmdr)"""

    class Test(Local):
        """run tests"""

        def prepare(self):
            return (self.local.FG, self.local['tox'])

    class Bump(Local):
        """bump package version (and optionally build and release)"""

        def __init__(self, parser):
            parser.add_argument(
                'part',
                choices=('major', 'minor', 'patch'),
                help="part of the version to be bumped",
            )
            parser.add_argument(
                '-b', '--build',
                action='store_true',
                help='build the new version',
            )
            parser.add_argument(
                '-r', '--release',
                action='store_true',
                help='release the new build',
            )

        def prepare(self, args, parser):
            (_code,
             stdout,
             _err) = yield self.local['bumpversion']['--list', args.part]

            if args.build:
                yield from self.root['build'].prepare()

                if args.release:
                    rel_args = copy.copy(args)
                    if stdout is None:
                        rel_args.version = ('DRY-RUN',)
                    else:
                        (version_match,) = re.finditer(
                            r'^new_version=([\d.]+)$',
                            stdout,
                            re.M,
                        )
                        rel_args.version = version_match.groups()
                    yield from self.root['release'].prepare(rel_args)
            elif args.release:
                parser.error('will not release package without build')

    class Build(Local):
        """build package"""

        def prepare(self):
            # determine current version
            config = configparser.ConfigParser()
            config.read('./setup.cfg')
            version = config['bumpversion']['current_version']

            # build pure python distribution
            yield self.local['python'][
                'setup.py',
                'sdist',
                'bdist_wheel',
            ]

            # build zipapp
            #
            # we want to encourage easy installation as just "manage". but,
            # until then, we want it to be properly labeled throughout its
            # distribution. so, we'll build it in a temporary directory and wrap
            # it in an otherwise-superfluous zip.
            #
            yield self.local['mkdir']['-p', './pyz/']

            (_code, stdout, _err) = yield self.local['mktemp'][
                '-d',
                '--tmpdir',
                'manage-XXXXXXXX',
            ]

            tmpdir = 'DRY-RUN' if stdout is None else stdout.strip()

            try:
                yield self.local['shiv'][
                    '-c', 'manage',
                    '-o', f'{tmpdir}/manage',
                    '--build-id', version,
                    '--platform-root',
                    '.',
                ]

                yield self.local['zip'][
                    '-j',
                    f'./pyz/manage-{version}.zip',
                    f'{tmpdir}/manage',
                ]
            finally:
                yield self.local['rm']['-r', tmpdir]

    class Release(Local):
        """upload package(s) to pypi"""

        def __init__(self, parser):
            parser.add_argument(
                'version',
                nargs='+',
            )

        def prepare(self, args):
            yield self.local['twine']['upload'][[f'dist/*{version}*' for version in args.version]]

            yield self.local['git']['push']
            yield self.local['git']['push', '--tags']

            for version in args.version:
                yield self.local['gh'][
                    'release',
                    'create',
                    version,
                    f'./pyz/manage-{version}.zip#manage-{version}',
                    '--generate-notes',
                    '--verify-tag',
                ]
