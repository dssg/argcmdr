import argparse
import collections
import importlib
import re
import sys

from descriptors import classproperty
from plumbum import colors


__version__ = '0.0.2'

__all__ = (
    'main',
    'Command',
    'RootCommand',
)


def friendly_version(version_info):
    return '.'.join(map(str, version_info[:3]))


def check_version(minimum_version, version_info=sys.version_info):
    if version_info < minimum_version:
        raise EnvironmentError(
            "{self} requires Python version {} or higher, not: {}"
            .format(
                *(friendly_version(info) for info in (minimum_version,
                                                      version_info)),
                self=sys.argv[0].strip('./'),
            )
        )


def main(command_class, minimum_version=(0,)):
    args = None
    try:
        check_version(minimum_version)
        parser = command_class.get_parser()
        args = parser.parse_args()
        args.func(args)
    except Exception as exc:
        if args is None or getattr(args, 'traceback', True):
            raise

        print(f"[{exc.__class__.__name__}]" | colors.yellow,
              str(exc) | colors.red)
        sys.exit(1)
    except KeyboardInterrupt:
        print("stopped")


def execute():
    try:
        manager = importlib.import_module('manage')
    except ImportError:
        # CWD may not be in PYTHONPATH (and that's OK)
        spec = importlib.util.spec_from_file_location('manage', 'manage.py')
        manager = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(manager)
        except FileNotFoundError as exc:
            print(f"[{exc.__class__.__name__}]" | colors.yellow,
                  str(exc) | colors.red,
                  end='\n\n')
            with colors.cyan:
                print("Hint: set PYTHONPATH to the directory containing your manage.py, e.g.:\n\n",
                      '\tPYTHONPATH=path/to/project manage ...')
            sys.exit(1)

    root_command = next(
        value for value in vars(manager).values()
        if (
            isinstance(value, type) and
            issubclass(value, RootCommand) and
            value is not RootCommand
        )
    )
    main(root_command)


exhaust_iterable = collections.deque(maxlen=0).extend


class Command:

    def __init__(self, parser):
        pass

    def __call__(self, args):
        args.parser.print_usage()

    @classproperty
    def name(cls):
        return cls.__name__.lower()

    @classproperty
    def help(cls):
        parts = re.split(r'(?:\. )|\n', cls.__doc__, 1)
        return parts[0]

    @classproperty
    def subcommands(cls):
        return [value for value in vars(cls).values()
                if isinstance(value, type) and issubclass(value, Command)]

    @classmethod
    def base_parser(cls):
        parser = argparse.ArgumentParser(description=cls.__doc__)
        parser.add_argument(
            '--tb', '--traceback',
            action='store_true',
            default=False,
            dest='traceback',
            help="print error tracebacks",
        )
        return parser

    @classmethod
    def build_interface(cls, parser=None):
        if parser is None:
            parser = cls.base_parser()

        command = cls(parser)
        parser.set_defaults(func=command, parser=parser)
        yield (parser, command)

        subparsers = None
        for subcommand in cls.subcommands:
            if subparsers is None:
                subparsers = parser.add_subparsers(
                    title="{} commands".format(cls.name),
                    help="available commands",
                )

            subparser = subparsers.add_parser(subcommand.name,
                                              description=subcommand.__doc__,
                                              help=subcommand.help)
            yield from subcommand.build_interface(subparser)

    @classmethod
    def extend_parser(cls, parser):
        interface = cls.build_interface(parser)
        exhaust_iterable(interface)

    @classmethod
    def get_parser(cls):
        parser = cls.base_parser()
        cls.extend_parser(parser)
        return parser


class RootCommand(Command):

    _registry_ = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry_ = []

    @classproperty
    def registry(cls):
        if cls._registry_ is not None:
            return cls._registry_[:]

    @classmethod
    def register(cls, subcommand):
        if cls._registry_ is None:
            raise TypeError(f"{cls.__name__} is abstract and may not register subcommands")

        cls._registry_.append(subcommand)
        return subcommand

    @classproperty
    def subcommands(cls):
        subcommands = super().subcommands
        if cls._registry_ is not None:
            subcommands += cls._registry_
        return subcommands
