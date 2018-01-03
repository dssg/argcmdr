import argparse
import collections
import importlib
import re
import sys

import plumbum
import plumbum.commands
from descriptors import classproperty
from plumbum import colors


__version__ = '0.0.4'

__all__ = (
    'main',
    'entrypoint',
    'Command',
    'RootCommand',
    'Local',
    'LocalRoot',
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
        args.__command__(args)
    except Exception as exc:
        if args is None or getattr(args, 'traceback', True):
            raise

        print(f"[{exc.__class__.__name__}]" | colors.yellow,
              str(exc) | colors.red)
        sys.exit(1)
    except KeyboardInterrupt:
        print("stopped")


def execute():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--manage-file')
    (args, _remainder) = parser.parse_known_args()

    # import manage.py
    manager = None

    if not args.manage_file:
        try:
            manager = importlib.import_module('manage')
        except ImportError:
            pass

    if not manager:
        # CWD may not be in PYTHONPATH (and that's OK);
        # or, may have specified alternative location
        file_path = args.manage_file or 'manage.py'
        spec = importlib.util.spec_from_file_location('manage', file_path)
        manager = importlib.util.module_from_spec(spec)
        dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(manager)
        except FileNotFoundError:
            print("could not import module 'manage' and file not found:" | colors.red,
                  file_path,
                  end='\n\n')
            with colors.cyan:
                print("hint: specify a manage file path via --manage-file, e.g.:",
                      '\tmanage --manage-file=path/to/project/manage-file.py ...',
                      "...or set PYTHONPATH to the directory containing your manage.py, e.g.:",
                      '\tPYTHONPATH=path/to/project manage ...',
                      sep='\n\n')
            sys.exit(1)
        finally:
            sys.dont_write_bytecode = dont_write_bytecode

    # determine entrypoint
    for command_filter in (
        _is_entrypoint,
        _is_root_command,
        _is_command,
    ):
        candidates = (value for value in vars(manager).values()
                      if command_filter(value))

        try:
            entrypoint = next(candidates)
        except StopIteration:
            # no matches for this filter. try the next one.
            continue

        try:
            next(candidates)
        except StopIteration:
            # only one match. run it!
            main(entrypoint)
            return

        print("multiple entrypoints found" | colors.red,
              end='\n\n')
        with colors.cyan:
            print("hint: define one root command or mark "
                  "an entrypoint with the entrypoint decorator")
        sys.exit(1)

    print("no entrypoint found. define at least one command." | colors.yellow)
    sys.exit(1)


def _is_entrypoint(obj):
    return getattr(obj, '_argcmdr_entrypoint_', False)


def _is_root_command(obj):
    return (isinstance(obj, type) and
            issubclass(obj, RootCommand) and
            obj is not RootCommand and
            obj is not LocalRoot)


def _is_command(obj):
    return (isinstance(obj, type) and
            issubclass(obj, Command) and
            obj is not Command and
            obj is not Local)


exhaust_iterable = collections.deque(maxlen=0).extend


class Command:

    def __init__(self, parser):
        pass

    def __call__(self, args):
        args.__parser__.print_usage()

    @classproperty
    def name(cls):
        return cls.__name__.lower()

    @classproperty
    def help(cls):
        if cls.__doc__ is None:
            return None

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
            '--manage-file',
            metavar='PATH',
            help="Path to a manage command file",
        )
        parser.add_argument(
            '--tb', '--traceback',
            action='store_true',
            default=False,
            dest='traceback',
            help="print error tracebacks",
        )
        return parser

    @classmethod
    def build_interface(cls, parser=None, chain=None, parents=()):
        if parser is None:
            parser = cls.base_parser()

        command = cls(parser)

        children = argparse.Namespace()
        if chain is not None:
            setattr(chain, cls.name, command)

        parser.set_defaults(
            __command__=command,
            __parser__=parser,
            __parents__=parents,
            __children__=children,
        )
        yield (parser, command)

        subparsers = None
        subparents = (command,) + parents
        for subcommand in cls.subcommands:
            if subparsers is None:
                subparsers = parser.add_subparsers(
                    title="{} commands".format(cls.name),
                    help="available commands",
                )

            subparser = subparsers.add_parser(subcommand.name,
                                              description=subcommand.__doc__,
                                              help=subcommand.help)
            yield from subcommand.build_interface(subparser,
                                                  children,
                                                  subparents)

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


class CacheDict(collections.defaultdict):

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)

        value = self[key] = self.default_factory(key)
        return value


class Local(Command):

    local = CacheDict(plumbum.local.__getitem__)

    @classmethod
    def base_parser(cls):
        parser = super().base_parser()
        parser.add_argument(
            '-q', '--quiet',
            action='store_false',
            default=True,
            dest='foreground',
            help="do not print command output",
        )
        return parser

    def __call__(self, args):
        commands = self.prepare(args)

        if commands is None:
            return

        if isinstance(commands, plumbum.commands.BaseCommand):
            commands = (commands,)

        for command in commands:
            if args.foreground:
                command & plumbum.FG
            else:
                command()

    def prepare(self, args):
        super().__call__(args)


class LocalRoot(Local, RootCommand):
    pass


def entrypoint(cls):
    if not isinstance(cls, type) or not issubclass(cls, Command):
        raise TypeError(f"inappropriate entrypoint instance of type {cls.__class__}")
    cls._argcmdr_entrypoint_ = True
    return cls
