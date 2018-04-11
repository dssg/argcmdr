import argparse
import collections
import enum
import functools
import importlib
import importlib.util
import inspect
import re
import sys

import plumbum
import plumbum.commands
from descriptors import classproperty
from plumbum import colors


__version__ = '0.5.0'

__all__ = (
    'cmd',
    'cmdmethod',
    'local',
    'localmethod',
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


def noop(*args, **kwargs):
    pass


def main(command_class,
         minimum_version=(0,),
         argv=None,
         outfile=sys.stdout,
         extend_parser=noop):
    args = None
    try:
        check_version(minimum_version)
        (parser, args) = command_class.get_parser()
        extend_parser(parser)
        parser.parse_args(argv, args)
        command = args.__command__
        command.call(args)
    except Exception as exc:
        if args is None or getattr(args, 'traceback', True):
            raise

        print(f"[{exc.__class__.__name__}]" | colors.yellow,
              str(exc) | colors.red,
              file=outfile)
        sys.exit(1)
    except KeyboardInterrupt:
        print("stopped", file=outfile)


def add_manage_file(parser):
    parser.add_argument(
        '--manage-file',
        metavar='PATH',
        help="path to a manage command file",
    )


def execute():
    parser = argparse.ArgumentParser(add_help=False)
    add_manage_file(parser)
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
            main(entrypoint, extend_parser=add_manage_file)
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

    command_lookup_error_message = (
        "command hierarchy indices must be str (to descend), or "
        "negative integer (to ascend), not %r"
    )

    def __init__(self, parser):
        self.__children__ = None
        self.__parents__ = None
        self._args = None

    def __call__(self, args):
        args.__parser__.print_usage()

    def __getitem__(self, key):
        if isinstance(key, (str, bytes)) or not isinstance(key, collections.Sequence):
            return self.__getitem__((key,))

        if not key:
            return self

        head = key[0]

        if isinstance(head, str):
            if head in self.__children__:
                item = self.__children__[head]
            else:
                raise KeyError(f"command {self.name} has no child {head!r}")
        elif isinstance(head, int):
            if head >= 0:
                raise ValueError(self.command_lookup_error_message % head)

            try:
                item = self.__parents__[-1 - head]
            except IndexError:
                raise IndexError(f"command {self.name} has no parent {head!r}")
        else:
            raise TypeError(self.command_lookup_error_message % head)

        return item.__getitem__(key[1:])

    @property
    def root(self):
        if self.__parents__:
            return self.__parents__[-1]

    @property
    def args(self):
        if getattr(self, '_args', None) is None:
            raise RuntimeError('parsed argument namespace not available at this stage')
        else:
            return self._args

    def call(self, args, target_name='__call__'):
        call_args = (args, args.__parser__)
        call_arg_count = len(call_args)

        target_callable = getattr(self, target_name)
        signature = inspect.signature(target_callable)
        parameters = [name for (index, (name, param)) in enumerate(signature.parameters.items())
                      if index < call_arg_count or param.default is param.empty]
        param_count = len(parameters)

        if param_count > call_arg_count:
            raise TypeError(
                f"{self.__class__.__name__}.{target_name}() "
                "requires too many positional arguments: " +
                ', '.join(repr(param) for param in parameters[call_arg_count:])
            )

        return target_callable(*call_args[:param_count])

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

    @staticmethod
    def base_namespace():
        return argparse.Namespace()

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
    def build_interface(cls, parser=None, namespace=None, chain=None, parents=()):
        if parser is None:
            parser = cls.base_parser()
        if namespace is None:
            namespace = cls.base_namespace()

        command = cls(parser)
        command.__parents__ = parents
        command.__children__ = {}
        command._args = namespace

        if chain is not None:
            chain[cls.name] = command

        parser.set_defaults(
            __command__=command,
            __parser__=parser,
        )
        yield (parser, namespace, command)

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
                                                  namespace,
                                                  command.__children__,
                                                  subparents)

    @classmethod
    def extend_parser(cls, parser, namespace):
        interface = cls.build_interface(parser, namespace)
        exhaust_iterable(interface)

    @classmethod
    def get_parser(cls):
        parser = cls.base_parser()
        namespace = cls.base_namespace()
        cls.extend_parser(parser, namespace)
        return (parser, namespace)


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

    # link common exceptions
    local.ProcessExecutionError = plumbum.ProcessExecutionError
    local.CommandNotFound = plumbum.CommandNotFound

    # ...and modifiers
    local.BG = plumbum.BG
    local.FG = plumbum.FG
    local.TEE = plumbum.TEE

    run_kws = frozenset(('retcode',))
    run_modifiers = frozenset((plumbum.BG, plumbum.FG, plumbum.TEE))

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
        parser.add_argument(
            '-d', '--dry-run',
            action='store_false',
            default=True,
            dest='execute_commands',
            help="do not execute commands, "
                 "but print what they are (unless --no-show is provided)",
        )
        parser.add_argument(
            '-s', '--show',
            action='store_true',
            default=None,
            dest='show_commands',
            help="print command expressions "
                 "(by default not printed unless dry-run)",
        )
        parser.add_argument(
            '--no-show',
            action='store_false',
            default=None,
            dest='show_commands',
            help="do not print command expressions "
                 "(by default not printed unless dry-run)",
        )
        return parser

    def __call__(self, args):
        commands = self.call(args, 'prepare')

        if commands is None:
            return

        if isinstance(commands, plumbum.commands.BaseCommand) or (
            isinstance(commands, (tuple, list)) and
            len(commands) == 2 and
            commands[0] in self.run_modifiers
        ):
            commands = (commands,)

        send = hasattr(commands, 'send')
        run_kwargs = {key: value for (key, value) in vars(self.prepare).items()
                      if key in self.run_kws}

        if args.show_commands is None:
            show_commands = not args.execute_commands
        else:
            show_commands = args.show_commands

        result = thrown = None
        empty_result = (None, None, None)
        iterator = iter(commands)

        while True:
            try:
                if send and result is not None:
                    command = iterator.send(result)
                elif send and thrown is not None:
                    command = iterator.throw(thrown)
                else:
                    command = next(iterator)
            except StopIteration:
                break

            if isinstance(command, (tuple, list)):
                (modifier, command) = command
            else:
                modifier = None

            if show_commands:
                print('>', command)

            if args.execute_commands:
                try:
                    if modifier is not None:
                        result = command & modifier(**run_kwargs)
                        if result is None:
                            result = empty_result
                    elif args.foreground:
                        result = command & plumbum.TEE(**run_kwargs)
                    else:
                        result = command.run(**run_kwargs)
                except Exception as exc:
                    if not send:
                        raise

                    result = None
                    thrown = exc
                else:
                    thrown = None
            else:
                result = empty_result

    def prepare(self, args):
        super().__call__(args)


class LocalRoot(Local, RootCommand):
    pass


#                                   #
# command manufacture via decorator #
#                                   #

unset = object()


class GeneratedCommand:
    """Mix-in for manufactured commands."""

    def __init__(self, parser):
        super().__init__(parser)

        for (args, kwargs) in self._args_:
            parser.add_argument(*args, **kwargs)


class CommandMethod:
    """Decorating descriptor producing a command functionality method
    which receives as its first argument its parent command instance.

    """
    def __init__(self, func):
        self.__func__ = func

    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        parent = instance[-1]
        return self.__func__.__get__(parent)


class WrappedCallable:
    """Wrapper allowing standard functions to be specified as class
    attributes which will not bind as methods.

    This wrapper hides functions' descriptor interface, such that, for
    example, functions intended as ``Enum`` values are not treated as
    methods (and thereby ignored as values).

    """
    def __init__(self, func):
        # Copy over useful, identifying attributes
        # But, disable attributes to copy by "update", which includes
        # __dict__, and thereby copies everything we're trying to hide
        functools.update_wrapper(self, func, updated=())

    def __call__(self, *args, **kwargs):
        return self.__wrapped__(*args, **kwargs)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.__wrapped__!r})"


c = WrappedCallable


class CallableEnum(enum.Enum):
    """Enum whose instances are callable and which invoke their values."""

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)


def noopl(x):
    return x


class CommandDecorator:
    """Decorate a callable to replace it with a manufactured command
    class.

    The callable is supplied as the manufactured command's functionality
    method, (*e.g.* either ``__call__`` or ``prepare``).

    A CLI parser argument may be specified in the initialization phase
    of the decorator instance, and/or through repeated decoration of
    the manufactured command.

    The manufactured command may be further customized through decorator
    initialization keyword flags ``local`` and ``root``, or by explicit
    specification of a custom base class.

    The binding of the decorated callable to the command instance, (and
    therefore the arguments it may expect to receive, such as ``self``),
    is *static* by default. However, if it is a ``Local`` command, the
    callable will instead receive its default binding, (*e.g.* as a
    command instance method if the callable is a standard function). The
    binding may be explicitly controlled by setting the ``binding``
    keyword to either a Boolean value or to a ``Binding`` instance.

    """
    class Binding(CallableEnum):

        default = c(noopl)
        static = c(staticmethod)
        parent = c(CommandMethod)

    def __init__(self,
                 *parser_args,
                 base=unset,
                 binding=unset,
                 local=False,
                 root=False,
                 **parser_kwargs):
        if (local or root) and base is not unset:
            raise TypeError("cannot apply 'local' or 'root' functionality to "
                            "arbitrary base")

        if base is unset:
            if local:
                self.base = LocalRoot if root else Local
            else:
                self.base = RootCommand if root else Command
        else:
            self.base = base

        if binding is unset:
            if issubclass(self.base, Local):
                self.binding = self.Binding.default
            else:
                self.binding = self.Binding.static
        elif isinstance(binding, bool):
            if binding:
                self.binding = self.Binding.default
            else:
                self.binding = self.Binding.static
        elif isinstance(binding, self.Binding):
            self.binding = binding
        else:
            raise TypeError('binding must be either bool, Binding or unset')

        self.args = (parser_args, parser_kwargs)

    def __call__(self, target):
        args = [self.args] if any(self.args) else []

        if inspect.isclass(target):
            if issubclass(target, GeneratedCommand):
                target._args_.extend(args)
                return target

        elif callable(target):
            call_name = 'prepare' if issubclass(self.base, Local) else '__call__'
            call_target = self.binding(target)

            return type(
                target.__name__,
                (GeneratedCommand, self.base),
                {
                    '_args_': args,
                    '__doc__': target.__doc__,
                    '__module__': target.__module__,
                    call_name: call_target,
                }
            )

        raise TypeError(f"unexpected command decoration target {target}")


def cmd(*args, **kwargs):
    """Decorate a callable to replace it with a manufactured command
    class.

    Extends the interface of ``CommandDecorator``, allowing the same
    ``cmd`` to be used as a decorator or as a decorator factory::

        @cmd(root=True)
        def build():
            ...

        @build.register
        @cmd
        def deploy():
            ...

    Further enables composition of configuration, for example via
    partials, as helpers.

    """
    try:
        (first, *remainder) = args
    except ValueError:
        pass
    else:
        if callable(first):
            return CommandDecorator(*remainder, **kwargs)(first)

    return CommandDecorator(*args, **kwargs)


local = functools.partial(cmd, local=True)

cmdmethod = functools.partial(cmd, binding=CommandDecorator.Binding.parent)

localmethod = functools.partial(local, binding=CommandDecorator.Binding.parent)


def entrypoint(cls):
    """Mark the decorated command as the intended entrypoint of the
    command module.

    """
    if not isinstance(cls, type) or not issubclass(cls, Command):
        raise TypeError(f"inappropriate entrypoint instance of type {cls.__class__}")
    cls._argcmdr_entrypoint_ = True
    return cls
