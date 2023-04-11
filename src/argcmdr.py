import argcomplete
import argparse
import collections
import collections.abc
import copy
import enum
import functools
import importlib
import importlib.util
import inspect
import os
import pkgutil
import re
import sys

import plumbum
import plumbum.commands
from plumbum import colors

from descriptors import (
    cachedproperty as _cachedproperty,
    classproperty as _classproperty,
)


__version__ = '1.0.1'

__all__ = (
    'cmd',
    'cmdmethod',
    'local',
    'localmethod',
    'main',
    'entrypoint',
    'init_package',
    'Command',
    'RootCommand',
    'Local',
    'LocalRoot',
)


def _friendly_version(version_info):
    return '.'.join(map(str, version_info[:3]))


def check_version(minimum_version, version_info=sys.version_info):
    if version_info < minimum_version:
        raise EnvironmentError(
            "{self} requires Python version {} or higher, not: {}"
            .format(
                *(_friendly_version(info) for info in (minimum_version,
                                                       version_info)),
                self=sys.argv[0].strip('./'),
            )
        )


def _noop(*args, **kwargs):
    pass


def main(command_class,
         minimum_version=(0,),
         argv=None,
         outfile=sys.stdout,
         extend_parser=_noop):
    args = None
    try:
        check_version(minimum_version)
        (parser, args) = command_class._get_parser_()
        extend_parser(parser)
        argcomplete.autocomplete(parser)
        parser.parse_args(argv, args)
        command = args._command_
        command.call()
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


MANAGE_FILE_PATHS = (
    os.path.join('manage', '__init__.py'),
    'manage.py',
)


def init_package(path=None, name='manage'):
    """Initialize (import) the submodules, and recursively the
    subpackages, of a "manage" package at ``path``.

    ``path`` may be specified as either a system directory path or a
    list of these.

    If ``path`` is unspecified, it is inferred from the already-imported
    "manage" top-level module.

    """
    if path is None:
        manager = sys.modules[name]
        init_package(manager.__path__, name)
        return

    if isinstance(path, str):
        init_package([path], name)
        return

    for module_info in pkgutil.walk_packages(path, f'{name}.'):
        if not module_info.ispkg:
            importlib.import_module(module_info.name)


def execute(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    add_manage_file(parser)
    (args, _remainder) = parser.parse_known_args(argv)

    # import manage.py / manage package
    manager = None

    # 1) NBD, already on the python-path
    if not args.manage_file:
        try:
            manager = importlib.import_module('manage')
        except ImportError:
            pass

    if not manager:
        # CWD may not be in PYTHONPATH (and that's OK);
        # or, may have specified alternative location
        if args.manage_file:
            # 2) alternative location specified
            if os.path.isdir(args.manage_file):
                file_path = os.path.join(args.manage_file, '__init__.py')
            else:
                file_path = args.manage_file
        else:
            # 3) we'll try the usual suspects
            # Note: *could* raise the error here, in a for/else block
            for file_path in MANAGE_FILE_PATHS:
                if os.path.isfile(file_path):
                    break

        spec = importlib.util.spec_from_file_location('manage', file_path)
        manager = importlib.util.module_from_spec(spec)

        # in case we're loading a package (with internal references)
        sys.modules['manage'] = manager

        # prevent __pycache__ clutter
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

    # auto-init manage package's submodules and subpackages
    auto_init_package = getattr(manager, '__auto_init_package__', True)
    submodule_search_locations = getattr(manager, '__path__', None)
    if auto_init_package and submodule_search_locations is not None:
        init_package(submodule_search_locations)

    # determine entrypoint
    for command_filter in (
        _is_entrypoint_,
        _is_root_command_,
        _is_command_,
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
            main(entrypoint, argv=argv, extend_parser=add_manage_file)
            return

        print("multiple entrypoints found" | colors.red,
              end='\n\n')
        with colors.cyan:
            print("hint: define one root command or mark "
                  "an entrypoint with the entrypoint decorator")
        sys.exit(1)

    print("no entrypoint found. define at least one command." | colors.yellow)
    sys.exit(1)


def _is_entrypoint_(obj):
    return getattr(obj, '_argcmdr_entrypoint_', False)


def _is_root_command_(obj):
    return (isinstance(obj, type) and
            issubclass(obj, RootCommand) and
            obj is not RootCommand and
            obj is not LocalRoot)


def _is_command_(obj):
    return (isinstance(obj, type) and
            issubclass(obj, Command) and
            obj is not Command and
            obj is not Local)


_exhaust_iterable = collections.deque(maxlen=0).extend

_command_lookup_error_message = ("command hierarchy indices must be str (to descend), or "
                                 "negative integer (to ascend), not %r")


class Command:

    #
    # interface *intended* for override/extension by subclasses
    #

    formatter_class = argparse.HelpFormatter

    @_classproperty
    def help(cls):
        if cls.__doc__ is None:
            return None

        parts = re.split(r'(?:\. )|\n', cls.__doc__, 1)
        return parts[0]

    @_classproperty
    def name(cls):
        return cls.__name__.lower()

    def __init__(self, parser):
        self._args_ = None
        self._parser_ = parser

        self._children_ = None
        self._parents_ = None

    def __call__(self, args):
        args._parser_.print_usage()

    #
    # public interface
    #

    def __getitem__(self, key):
        if isinstance(key, (str, bytes)) or not isinstance(key, collections.abc.Sequence):
            return self.__getitem__((key,))

        if not key:
            return self

        head = key[0]

        if isinstance(head, str):
            item = self._get_children_().get(head)

            if item is None:
                raise KeyError(f"command {self.name} has no child {head!r}")
        elif isinstance(head, int):
            if head >= 0:
                raise ValueError(_command_lookup_error_message % head)

            try:
                item = self._get_parents_()[-1 - head]
            except IndexError:
                raise IndexError(f"command {self.name} has no parent {head!r}")
        else:
            raise TypeError(_command_lookup_error_message % head)

        return item.__getitem__(key[1:])

    def __iter__(self):
        yield from self._get_children_().values()

    @property
    def root(self):
        try:
            return self._get_parents_()[-1]
        except IndexError:
            return None

    def get_args(self):
        args = getattr(self, '_args_', None)  # user *may* neglect to super().__init__

        if args is None:
            raise RuntimeError('parsed argument namespace not available at this stage')

        return args

    @property
    def args(self):
        args = self.get_args()

        if args._command_ is not self:
            # The property is here made consistent with the argumentation of
            # the delegate() interface; and, methods relying on this property
            # are thereby enabled regardless of whether their associated
            # command was invoked directly or via delegation.
            #
            # Note: It is arguable that this is unnecessary in the case that
            # the requesting command is an ancestor of the CLI-invoked
            # command -- in this case, all of the requesting command's
            # arguments should be filled, and there's little need.
            #
            # This condition could be tested here with the expression:
            #
            #     self (not) in args._command_._parents_
            #
            # (and in which case, for consistency, delegate() should perhaps be
            # modified to also pass non-delegate args to the ancestor command).
            #
            # However, more than just the CLI arguments, delegate_args further
            # populates the command's own sub-parser. And so, for now, for
            # consistency and relative simplicity, all commands will *always*
            # get their "own" args and parser, via delegate_args whenever it is
            # not the CLI-invoked command.
            #
            return self.delegate_args

        return args

    @_cachedproperty
    def delegate_args(self):
        args = copy.copy(self.get_args())
        args._parser_ = self._parser_

        for action in self._parser_._actions:
            args.__dict__.setdefault(action.dest, action.default)

        for default in self._parser_._defaults.items():
            args.__dict__.setdefault(*default)

        return args

    @property
    def parser(self):
        return getattr(self, '_parser_', None)  # user *may* neglect to super().__init__

    def call(self, *additional):
        return self.delegate('__call__', *additional)

    def delegate(self, method_name='__call__', *additional):
        nspace = self.args
        call_args = (nspace, nspace._parser_) + additional
        call_arg_count = len(call_args)

        target_callable = getattr(self, method_name)
        signature = inspect.signature(target_callable)
        parameters = [name for (index, (name, param)) in enumerate(signature.parameters.items())
                      if index < call_arg_count or param.default is param.empty]
        param_count = len(parameters)

        if param_count > call_arg_count:
            raise TypeError(
                f"{self.__class__.__name__}.{method_name}() "
                "requires too many positional arguments: " +
                ', '.join(repr(param) for param in parameters[call_arg_count:])
            )

        return target_callable(*call_args[:param_count])

    #
    # interface which *may* be overriden/extended by subclasses to customize operation
    #

    _allow_traceback_ = True

    @_classproperty
    def _subcommands_(cls):
        return [value for value in vars(cls).values()
                if isinstance(value, type) and issubclass(value, Command)]

    @staticmethod
    def _new_namespace_():
        return argparse.Namespace()

    @classmethod
    def _new_parser_(cls):
        parser = argparse.ArgumentParser(description=cls.__doc__,
                                         formatter_class=cls.formatter_class)

        if cls._allow_traceback_:
            parser.add_argument(
                '--tb', '--traceback',
                action='store_true',
                default=False,
                dest='traceback',
                help="print error tracebacks",
            )

        return parser

    @staticmethod
    def _new_subparser_(subparsers, subcommand):
        return subparsers.add_parser(subcommand.name,
                                     description=subcommand.__doc__,
                                     help=subcommand.help,
                                     formatter_class=subcommand.formatter_class)

    @classmethod
    def _build_interface_(cls, parser=None, namespace=None, chain=None, parents=()):
        if parser is None:
            parser = cls._new_parser_()
        if namespace is None:
            namespace = cls._new_namespace_()

        command = cls(parser)
        command._parents_ = parents
        command._children_ = {}
        command._args_ = namespace
        command._parser_ = parser  # user *may* neglect to super().__init__

        if chain is not None:
            chain[cls.name] = command

        parser.set_defaults(
            _command_=command,
            _parser_=parser,
        )
        yield (parser, namespace, command)

        subparsers = None
        subparents = (command,) + parents
        for subcommand in cls._subcommands_:
            if subparsers is None:
                subparsers = parser.add_subparsers(
                    title="{} commands".format(cls.name),
                    help="available commands",
                )

            subparser = cls._new_subparser_(subparsers, subcommand)

            yield from subcommand._build_interface_(subparser,
                                                    namespace,
                                                    command._children_,
                                                    subparents)

    @classmethod
    def _init_parser_(cls, parser, namespace):
        interface = cls._build_interface_(parser, namespace)
        _exhaust_iterable(interface)

    @classmethod
    def _get_parser_(cls):
        parser = cls._new_parser_()
        namespace = cls._new_namespace_()
        cls._init_parser_(parser, namespace)
        return (parser, namespace)

    #
    # internal helpers
    #

    def _get_children_(self):
        children = getattr(self, '_children_', None)  # user *may* neglect to super().__init__

        if children is None:
            raise RuntimeError('hierarchy of constructed commands not available at this stage')

        return children

    def _get_parents_(self):
        parents = getattr(self, '_parents_', None)  # user *may* neglect to super().__init__

        if parents is None:
            raise RuntimeError('hierarchy of constructed commands not available at this stage')

        return parents


class RootCommand(Command):

    _registry_ = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry_ = []

    @classmethod
    def register(cls, subcommand):
        if cls._registry_ is None:
            raise TypeError(f"{cls.__name__} is abstract and may not register subcommands")

        cls._registry_.append(subcommand)
        return subcommand

    @_classproperty
    def _subcommands_(cls):
        subcommands = super()._subcommands_
        if cls._registry_ is not None:
            subcommands += cls._registry_
        return subcommands


class CacheDict(collections.defaultdict):

    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)

        value = self[key] = self.default_factory(key)
        return value


class _SHH(plumbum.commands.ExecutionModifier):
    """plumbum execution modifier to ensure output is not echoed to terminal

    essentially a no-op, this may be used to override argcmdr settings
    and cli flags controlling this feature, on a line-by-line basis, to
    hide unnecessary or problematic (e.g. highly verbose) command output.

    """
    __slots__ = ('retcode', 'timeout')

    def __init__(self, retcode=0, timeout=None):
        self.retcode = retcode
        self.timeout = timeout

    def __rand__(self, cmd):
        return cmd.run(retcode=self.retcode, timeout=self.timeout)


SHH = _SHH()


class Local(Command):

    local = CacheDict(plumbum.local.__getitem__)

    # link common exceptions
    local.ProcessExecutionError = plumbum.ProcessExecutionError
    local.CommandNotFound = plumbum.CommandNotFound

    # ...and modifiers
    local.BG = plumbum.BG
    local.FG = plumbum.FG
    local.TEE = plumbum.TEE

    # ...(as well as our own)
    local.SHH = SHH

    _run_kws_ = frozenset(('retcode', 'timeout'))

    @classmethod
    def _new_parser_(cls):
        parser = super()._new_parser_()
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

    def _show_command_(self, command, force=False):
        if force or self.args.show_commands or (
            self.args.show_commands is None and
            not self.args.execute_commands
        ):
            # Due to plumbum issue #398 we can't do this:
            #
            # print('>', colors['#5FAF5F'] | str(command))
            #
            # whenever the command has been supplied stdin.
            formulation = ' '.join(map(str, command.formulate()))
            print('>', colors['#5FAF5F'] | formulation)

    def delegate(self, method_name='prepare', *additional):
        return super().delegate(method_name, self.local, *additional)

    def __call__(self, args):
        commands = self.delegate()

        if commands is None:
            return

        if isinstance(commands, plumbum.commands.BaseCommand) or (
            isinstance(commands, (tuple, list)) and
            len(commands) == 2 and
            isinstance(commands[0], plumbum.commands.ExecutionModifier)
        ):
            commands = (commands,)

        send = hasattr(commands, 'send')
        run_kwargs = {key: getattr(self.prepare, key)
                      for key in self._run_kws_ & self.prepare.__dict__.keys()}

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

            self._show_command_(command)

            if args.execute_commands:
                try:
                    if modifier is not None:
                        if run_kwargs:
                            result = command & modifier(**run_kwargs)
                        else:
                            result = command & modifier

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

Unset = object()


class GeneratedCommand:
    """Mix-in for manufactured commands."""

    _parser_args_ = ()

    def __init__(self, parser):
        super().__init__(parser)

        for (args, kwargs) in self._parser_args_:
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


_c = WrappedCallable


class CallableEnum(enum.Enum):
    """Enum whose instances are callable and which invoke their values."""

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)


def _noopl(x):
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

        default = _c(_noopl)
        static = _c(staticmethod)
        parent = _c(CommandMethod)

    def __init__(self,
                 *parser_args,
                 base=Unset,
                 binding=Unset,
                 local=False,
                 root=False,
                 method_name=None,
                 **parser_kwargs):
        if (local or root) and base is not Unset:
            raise TypeError("cannot apply 'local' or 'root' functionality to "
                            "arbitrary base")

        if base is Unset:
            if local:
                self.base = LocalRoot if root else Local
            else:
                self.base = RootCommand if root else Command
        else:
            self.base = base

        if binding is Unset:
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
            raise TypeError('binding must be either bool, Binding or Unset')

        if method_name is None:
            self.method_name = 'prepare' if issubclass(self.base, Local) else '__call__'
        else:
            self.method_name = method_name

        self.args = (parser_args, parser_kwargs)

    def __call__(self, target):
        args = [self.args] if any(self.args) else []

        if inspect.isclass(target):
            if issubclass(target, GeneratedCommand):
                target._parser_args_.extend(args)
                return target

        elif callable(target):
            return type(
                target.__name__,
                (GeneratedCommand, self.base),
                {
                    '_parser_args_': args,
                    '__doc__': target.__doc__,
                    '__module__': target.__module__,
                    self.method_name: self.binding(target),
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


#                   #
# Interface helpers #
#                   #

# TODO: convert to package and move these argparse helpers to submodule


def store_env_override(option_strings,
                       dest,
                       envvar,
                       nargs=None,
                       default=None,
                       type=None,
                       choices=None,
                       description=None,
                       help=None,
                       metavar=None):
    """Construct an argparse action which stores the value of a command
    line option to override a corresponding value in the process
    environment.

    If the environment variable is not empty, then no override is
    required. If the environment variable is empty, and no default is
    provided, then the "option" is required.

    In the case of a default value which is a *transformation* of the
    single environment variable, this default may be provided as a
    callable, (*e.g.* as a lambda function).

    Rather than have to fully explain the relationship of this
    environment-backed option, help text may be generated from a
    provided description.

    """
    if envvar == '':
        raise ValueError("unsupported environment variable name", envvar)

    envvalue = os.getenv(envvar)

    if callable(default):
        default_value = default(envvalue)
    elif envvalue:
        default_value = envvalue
    else:
        default_value = default

    if description and help:
        raise ValueError(
            "only specify help to override its optional generation from "
            "description -- not both"
        )
    elif description:
        if default_value:
            help = '{} (default {} envvar {}: {})'.format(
                description,
                'provided by' if default is None else 'derived from',
                envvar,
                default_value,
            )
        else:
            help = (f'{description} (required because '
                    f'envvar {envvar} is empty)')

    return argparse._StoreAction(
        option_strings=option_strings,
        dest=dest,
        nargs=nargs,
        const=None,
        default=default_value,
        type=type,
        choices=choices,
        required=(not default_value),
        help=help,
        metavar=metavar,
    )
