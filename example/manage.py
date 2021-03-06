import os

from argcmdr import Local, main


class Management(Local):
    """manage deployment"""

    def __init__(self, parser):
        parser.add_argument(
            '-e', '--env',
            choices=('development', 'production'),
            default='development',
            help="target environment",
        )

    class Build(Local):
        """build app"""

        def prepare(self, args):
            req_path = os.path.join('requirements', f'{args.env}.txt')
            yield self.local['pip']['-r', req_path]

    class Deploy(Local):
        """deploy app"""

        def prepare(self, args):
            yield self.local['eb']['deploy', args.env]
