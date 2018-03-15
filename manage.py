"""argcmdr's own management module"""
from argcmdr import Local


class Manage(Local):
    """manage development of argcmdr ... (with argcmdr)"""

    class Test(Local):
        """run tests"""

        def prepare(self):
            return self.local['tox']

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
