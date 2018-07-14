from argcmdr import cmd

import test_argcmdr


@cmd('target')
def main(args):
    target = getattr(test_argcmdr, args.target)
    target.declare_success()
