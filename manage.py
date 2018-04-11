"""argcmdr's own management module"""
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
                yield self.root['build'].prepare()

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
                    yield self.root['release'].prepare(rel_args)
            elif args.release:
                parser.error('will not release package without build')

    class Build(Local):
        """build package"""

        def prepare(self):
            return self.local['python'][
                'setup.py',
                'sdist',
                'bdist_wheel',
            ]

    class Release(Local):
        """upload package(s) to pypi"""

        def __init__(self, parser):
            parser.add_argument(
                'version',
                nargs='*',
            )

        def prepare(self, args):
            if args.version:
                target = [f'dist/*{version}*' for version in args.version]
            else:
                target = 'dist/*'
            return self.local['twine']['upload'][target]
