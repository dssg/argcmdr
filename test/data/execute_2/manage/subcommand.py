from argcmdr import cmd

from .main import main

import test_argcmdr


@main.register
@cmd('target')
def subcommand(args):
    target = getattr(test_argcmdr, args.target)
    target.declare_success()
