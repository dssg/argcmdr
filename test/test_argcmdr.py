import argparse
import io
import os
import pdb
import re
import subprocess
import types
import unittest
import sys
import tempfile
import traceback
from unittest import mock

import plumbum.commands

from argcmdr import (
    cmd,
    Command,
    CommandMethod,
    execute,
    GeneratedCommand,
    _exhaust_iterable,
    local,
    Local,
    localmethod,
    main,
    RootCommand,
)


ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

TEST_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(TEST_DIR, 'data')


def pm():
    info = sys.exc_info()
    traceback.print_exception(*info)
    pdb.post_mortem(info[2])


class TryCommandTestCase(unittest.TestCase):

    def try_command(self, command_cls):
        # ensure parser is available to tests with nested command defns
        (self.parser, args) = command_cls._get_parser_()
        self.parser.parse_args([], args)
        command = args._command_
        command.call()


class TryMainTestCase(unittest.TestCase):

    def try_main(self, *args):
        try:
            main(*args, argv=[])
        except SystemExit as exc:
            self.fail(exc)


class TestCommandGetItem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.Leaf1 = type('Leaf1', (Command,), {})
        cls.Leaf2 = type('Leaf2', (Command,), {})
        cls.Branch1 = type('Branch1', (Command,), {
            'Leaf1': cls.Leaf1,
        })
        cls.Branch2 = type('Branch2', (Command,), {
            'Leaf2': cls.Leaf2,
        })
        cls.Root = type('Root', (Command,), {
            'Branch1': cls.Branch1,
            'Branch2': cls.Branch2,
        })

    def setUp(self):
        interface = self.Root._build_interface_()
        (_parser, _namespace, self.root) = next(interface)
        _exhaust_iterable(interface)

    def test_identity(self):
        self.assertIs(self.root[()], self.root)

    def test_identity_list(self):
        self.assertIs(self.root[[]], self.root)

    def test_descend_1(self):
        self.assertIs(self.root['branch1'].__class__, self.Branch1)

    def test_descend_2(self):
        self.assertIs(self.root['branch1', 'leaf1'].__class__, self.Leaf1)

    def test_descend_2_list(self):
        self.assertIs(self.root[['branch1', 'leaf1']].__class__, self.Leaf1)

    def test_ascend_1(self):
        leaf1 = self.root['branch1', 'leaf1']
        self.assertIs(leaf1.__class__, self.Leaf1)
        self.assertIs(leaf1[-1].__class__, self.Branch1)

    def test_ascend_2(self):
        leaf1 = self.root['branch1', 'leaf1']
        self.assertIs(leaf1.__class__, self.Leaf1)
        self.assertIs(leaf1[-2], self.root)

    def test_strafe(self):
        branch1 = self.root['branch1']
        self.assertIs(branch1[-1, 'branch2'].__class__, self.Branch2)

    def test_missing_key(self):
        with self.assertRaises(LookupError):
            self.root['branch3']

    def test_missing_index(self):
        with self.assertRaises(LookupError):
            self.root[-1]

    def test_bad_key(self):
        with self.assertRaises(TypeError):
            self.root[None]

    def test_bad_index(self):
        with self.assertRaises(ValueError):
            self.root[0]


class TestCommandGetItemError(unittest.TestCase):

    def test_get_item_error(test):
        class BadGetItemCommand(Command):

            def __init__(self, parser):
                super().__init__(parser)

                with test.assertRaises(RuntimeError):
                    self['nope']

            def __call__(self):
                pass

        next(BadGetItemCommand._build_interface_())

    def test_get_item_error_quick(test):
        class QuickBadGetItemCommand(Command):

            def __init__(self, _parser):
                with test.assertRaises(RuntimeError):
                    self['nope']

            def __call__(self):
                pass

        next(QuickBadGetItemCommand._build_interface_())


class TestSubcommandIteration(unittest.TestCase):

    @staticmethod
    def build_interface(command):
        interface = command._build_interface_()
        (_parser, _namespace, root) = next(interface)
        _exhaust_iterable(interface)
        return root

    def test_iter_children(self):
        Leaf1 = type('Leaf1', (Command,), {})
        Leaf2 = type('Leaf2', (Command,), {})
        Branch1 = type('Branch1', (Command,), {
            'Leaf1': Leaf1,
        })
        Branch2 = type('Branch2', (Command,), {
            'Leaf2': Leaf2,
        })
        Root = type('Root', (Command,), {
            'Branch1': Branch1,
            'Branch2': Branch2,
        })

        root = self.build_interface(Root)

        self.assertEqual(list(root), [root['branch1'], root['branch2']])
        self.assertEqual(list(root['branch1']), [root['branch1', 'leaf1']])
        self.assertEqual(list(root['branch2']), [root['branch2', 'leaf2']])
        self.assertEqual(list(root['branch1', 'leaf1']), [])
        self.assertEqual(list(root['branch2', 'leaf2']), [])

    def test_iter_error(test):
        class BadIterCommand(Command):

            def __init__(self, parser):
                super().__init__(parser)

                with test.assertRaises(RuntimeError):
                    list(self)

            def __call__(self):
                pass

        test.build_interface(BadIterCommand)

    def test_iter_error_quick(test):
        class QuickBadIterCommand(Command):

            def __init__(self, _parser):
                with test.assertRaises(RuntimeError):
                    list(self)

            def __call__(self):
                pass

        test.build_interface(QuickBadIterCommand)


class TestCommandDelegation(unittest.TestCase):

    def test_delegation_to_child(test):
        @cmd('--no-eat', action='store_false', default=True, dest='should_eat')
        @cmd(root=True, binding=True)
        def root(self, args):
            test.assertTrue(args.should_eat)
            test.assertFalse(hasattr(args, 'this_food'))
            test.assertIs(args, self.get_args())

            # This would fail!
            # (forcing Child to handle missing 'this_food')
            # self['child'](args)
            #
            # This won't ;)
            self['child'].delegate()

        @root.register
        @cmd('--food', default='snacks', dest='this_food')
        @cmd(binding=True)
        def child(self, args):
            # target command's args populated regardless
            test.assertTrue(args.should_eat)

            # delegation should populate this command's defaults
            test.assertEqual(args.this_food, 'snacks')

            # ...in args property as well
            test.assertEqual(self.args.this_food, 'snacks')

            # self.args is self.delegate_args
            test.assertIs(self.args, self.delegate_args)

            # ...is args
            test.assertIs(args, self.args)

            # ...not the "real" args
            test.assertIsNot(args, self.get_args())

            # ...only the target gets those:
            test.assertIs(self.root.args, self.get_args())

        (parser, args) = root._get_parser_()
        parser.parse_args([], args)
        args._command_.call()

    def test_delegation_to_root(test):
        @cmd('--no-eat', action='store_false', default=True, dest='should_eat')
        @cmd(root=True, binding=True)
        def root(self, args, parser):
            # root *also* has child's args, because child was called
            test.assertTrue(args.should_eat)
            test.assertEqual(args.this_food, 'snacks')

            # root gets delegate_args -- even though it doesn't *strictly* need it
            #
            # (child's args are superset of root's, so this could be omitted in this case,
            # perhaps as an optimization.)
            #
            # however, this way, root gets access to *its* subparser, (on the off-chance that
            # that matters). and, we're just consistent and straight-forward about it.
            test.assertIs(args, self.args)
            test.assertIs(self.args, self.delegate_args)

            test.assertIs(parser, args._parser_)
            test.assertIs(parser, self._parser_)

        @root.register
        @cmd('--food', default='snacks', dest='this_food')
        @cmd(binding=True)
        def child(self, args):
            test.assertTrue(args.should_eat)
            test.assertEqual(args.this_food, 'snacks')

            # self.args is NOT self.delegate_args
            test.assertIs(args, self.get_args())
            test.assertIs(args, self.args)
            test.assertIsNot(self.args, self.delegate_args)

            self.root.delegate()

        (parser, args) = root._get_parser_()
        parser.parse_args(['child'], args)
        args._command_.call()

    def test_delegation_to_sibling(test):
        @cmd('--no-eat', action='store_false', default=True, dest='should_eat', root=True)
        def root():
            raise AssertionError("I should not be invoked")

        @root.register
        @cmd('--candy', default='jelly beans', dest='this_candy', binding=True)
        def left(self, args, parser):
            test.assertTrue(args.should_eat)
            test.assertEqual(args.this_food, 'snacks')

            # delegation should populate this command's defaults
            test.assertEqual(args.this_candy, 'jelly beans')

            # self.args is self.delegate_args
            test.assertIs(self.args, self.delegate_args)

            # ...is args
            test.assertIs(args, self.args)

            # ...not the "real" args
            test.assertIsNot(args, self.get_args())

        @root.register
        @cmd('--food', default='snacks', dest='this_food', binding=True)
        def right(self, args):
            test.assertTrue(args.should_eat)
            test.assertEqual(args.this_food, 'snacks')

            test.assertFalse(hasattr(args, 'this_candy'))

            # self.args is NOT self.delegate_args
            test.assertIs(args, self.get_args())
            test.assertIs(args, self.args)
            test.assertIsNot(self.args, self.delegate_args)

            self[-1, 'left'].delegate()

        (parser, args) = root._get_parser_()
        parser.parse_args(['right'], args)
        args._command_.call()

    def test_arbitrary_access(test):
        @cmd('--no-eat', action='store_false', default=True, dest='should_eat', root=True)
        def root():
            raise AssertionError("I should not be invoked")

        @root.register
        class Left(Command):

            def __init__(self, parser):
                parser.add_argument(
                    '--candy',
                    default='jelly beans',
                    dest='this_candy',
                )

            def __call__(self):
                raise AssertionError("I should not be invoked")

            def method(self):
                test.assertTrue(self.args.should_eat)
                test.assertEqual(self.args.this_food, 'snacks')

                # delegation should populate this command's defaults
                test.assertEqual(self.args.this_candy, 'jelly beans')

                # self.args is self.delegate_args
                test.assertIs(self.args, self.delegate_args)

                # ...not the "real" args
                test.assertIsNot(self.args, self.get_args())

        @root.register
        @cmd('--food', default='snacks', dest='this_food', binding=True)
        def right(self, args):
            test.assertTrue(args.should_eat)
            test.assertEqual(args.this_food, 'snacks')

            test.assertFalse(hasattr(args, 'this_candy'))

            # self.args is NOT self.delegate_args
            test.assertIs(args, self.get_args())
            test.assertIs(args, self.args)
            test.assertIsNot(self.args, self.delegate_args)

            self[-1, 'left'].method()

        (parser, args) = root._get_parser_()
        parser.parse_args(['right'], args)
        args._command_.call()

    def test_parser_defaults(test):
        """delegate_args respects ArgumentParser.set_defaults"""
        class Root(RootCommand):

            def __init__(self, parser):
                parser.add_argument(
                    '--no-eat',
                    action='store_false',
                    default=True,
                    dest='should_eat',
                )

                parser.set_defaults(root='so cool')

            def __call__(self, args):
                test.assertTrue(args.should_eat)
                test.assertEqual(args.root, 'so cool')
                test.assertFalse(hasattr(args, 'this_food'))
                test.assertIs(args, self.get_args())

                self['child'].delegate()

        @Root.register
        class Child(Command):

            def __init__(self, parser):
                parser.add_argument(
                    '--food',
                    default='snacks',
                    dest='this_food',
                )

                parser.set_defaults(child='even cooler')

            def __call__(self, args):
                test.assertTrue(args.should_eat)
                test.assertEqual(args.root, 'so cool')

                # delegation should populate this command's defaults
                test.assertEqual(args.this_food, 'snacks')
                test.assertEqual(args.child, 'even cooler')

                # self.args is self.delegate_args
                test.assertIs(args, self.args)
                test.assertIs(self.args, self.delegate_args)

                # ...not the "real" args
                test.assertIsNot(args, self.get_args())

        (parser, args) = Root._get_parser_()
        parser.parse_args([], args)
        args._command_.call()

    def test_delegation_to_method(test):
        """command may (re)-delegate to named method"""
        @cmd(binding=True, root=True)
        def root(context, args):
            test.assertFalse(hasattr(args, 'argument'))

            context['child'].delegate()

        @root.register
        class Child(Command):

            run_count = 0

            def __init__(self, parser):
                parser.add_argument(
                    '--nope',
                    dest='argument',
                    action='store_false',
                )

            def __call__(self, args):
                test.assertTrue(getattr(args, 'argument', None))

                self.delegate('other')

            def other(self, args):
                self.__class__.run_count += 1

                test.assertTrue(getattr(args, 'argument', None))

        (parser, args) = root._get_parser_()
        parser.parse_args([], args)
        args._command_.call()

        test.assertEqual(Child.run_count, 1)


class TestCommandRoot(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.Leaf = type('Leaf', (Command,), {})
        cls.Branch = type('Branch', (Command,), {
            'Leaf': cls.Leaf,
        })
        cls.Root = type('Root', (Command,), {
            'Branch': cls.Branch,
        })

    def setUp(self):
        for (_parser, _namespace, command) in self.Root._build_interface_():
            setattr(self, command.name, command)

    def test_root_0(self):
        self.assertIsNone(self.root.root)

    def test_root_1(self):
        self.assertIs(self.branch.root, self.root)

    def test_root_2(self):
        self.assertIs(self.leaf.root, self.root)


class TestMainCallSignature(TryMainTestCase):

    def test_simple(self):
        class Simple(Command):

            def __call__(self_, args):
                self.assertIsInstance(self_, Simple)
                self.assertIsInstance(args, argparse.Namespace)

        self.try_main(Simple)

    def test_deep(self):
        class Deep(Command):

            def __call__(self_, args, parser):
                self.assertIsInstance(self_, Deep)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIsInstance(parser, argparse.ArgumentParser)

        self.try_main(Deep)

    def test_fancy(self):
        class Fancy(Command):

            def __call__(self_, args, parser, lang='en'):
                self.assertIsInstance(self_, Fancy)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIsInstance(parser, argparse.ArgumentParser)
                self.assertEqual(lang, 'en')

        self.try_main(Fancy)

    def test_lame(self):
        class Lame(Command):

            def __call__(self_):
                self.assertIsInstance(self_, Lame)

        self.try_main(Lame)

    def test_bad(self):
        class Bad(Command):

            def __call__(self_, args, parser, lang):
                self.fail("how did this happen?")

        outfile = io.StringIO()
        with self.assertRaises(SystemExit) as context:
            main(Bad, argv=[], outfile=outfile)

        exc = context.exception.__context__
        self.assertIsInstance(exc, TypeError)
        self.assertEqual(exc.args, ("Bad.__call__() requires too many "
                                    "positional arguments: 'lang'",))
        self.assertIn(exc.args[0], outfile.getvalue())

    def test_tricky(self):
        class Tricky(Command):

            def __call__(self_, args, parser=None, lang='en'):
                self.assertIsInstance(self_, Tricky)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIsInstance(parser, argparse.ArgumentParser)
                self.assertEqual(lang, 'en')

        self.try_main(Tricky)


class TestPrepareCallSignature(TryCommandTestCase):

    def test_simple(self):
        class Simple(Local):

            def prepare(self_, args):
                self.assertIsInstance(self_, Simple)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args._command_, self_)
                self.assertIs(args._parser_, self.parser)

        self.try_command(Simple)

    def test_deep(self):
        class Deep(Local):

            def prepare(self_, args, parser):
                self.assertIsInstance(self_, Deep)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args._command_, self_)
                self.assertIs(args._parser_, self.parser)
                self.assertIs(parser, self.parser)

        self.try_command(Deep)

    def test_local(self):
        class DeepLocal(Local):

            def prepare(self_, args, parser, local):
                self.assertIsInstance(self_, DeepLocal)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args._command_, self_)
                self.assertIs(args._parser_, self.parser)
                self.assertIs(parser, self.parser)
                self.assertIs(local, self_.local)

        self.try_command(DeepLocal)

    def test_fancy(self):
        class Fancy(Local):

            def prepare(self_, args, parser, local, lang='en'):
                self.assertIsInstance(self_, Fancy)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args._command_, self_)
                self.assertIs(args._parser_, self.parser)
                self.assertIs(parser, self.parser)
                self.assertEqual(lang, 'en')

        self.try_command(Fancy)

    def test_lame(self):
        class Lame(Local):

            def prepare(self_):
                self.assertIsInstance(self_, Lame)

        self.try_command(Lame)

    def test_bad(self):
        class Bad(Local):

            def prepare(self_, args, parser, local, lang):
                self.fail("how did this happen?")

        with self.assertRaises(TypeError) as context:
            self.try_command(Bad)

        exc = context.exception
        self.assertIsInstance(exc, TypeError)
        self.assertEqual(exc.args, ("Bad.prepare() requires too many "
                                    "positional arguments: 'lang'",))

    def test_tricky(self):
        class Tricky(Local):

            def prepare(self_, args, parser=None, local=None, lang='en'):
                self.assertIsInstance(self_, Tricky)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args._command_, self_)
                self.assertIs(args._parser_, self.parser)
                self.assertIs(parser, self.parser)
                self.assertEqual(lang, 'en')

        self.try_command(Tricky)


class TestArgsProperty(TryMainTestCase):

    def test_identity(test):
        class ArgsCommand(Command):

            def __call__(self, args):
                test.assertIs(self.args, args)
                test.assertIs(self._args_, args)

        test.try_main(ArgsCommand)

    def test_access_error(test):
        class BadArgsCommand(Command):

            def __init__(self, _parser):
                with test.assertRaises(RuntimeError):
                    self.args

            def __call__(self):
                pass

        test.try_main(BadArgsCommand)

    def test_set_error(test):
        class BadArgsCommand(Command):

            def __init__(self, _parser):
                with test.assertRaises(AttributeError):
                    self.args = None

            def __call__(self):
                pass

        test.try_main(BadArgsCommand)


class TestParserProperty(TryMainTestCase):

    def test_identity(test):
        class ParserCommand(Command):

            def __init__(self, parser):
                super().__init__(parser)
                test.assertIs(self.parser, parser)
                test.assertIs(self._parser_, parser)

            def __call__(self, args, parser):
                test.assertIs(self.parser, parser)
                test.assertIs(self._parser_, parser)

        test.try_main(ParserCommand)

    def test_identity_no_super(test):
        class QuickParserCommand(Command):

            def __init__(self, parser):
                test.assertIs(self.parser, None)
                test.assertFalse(hasattr(self, '_parser_'))
                test.assertIsNot(parser, None)

            def __call__(self, args, parser):
                test.assertIs(self.parser, parser)
                test.assertIs(self._parser_, parser)
                test.assertIsNot(parser, None)

        test.try_main(QuickParserCommand)

    def test_set_error(test):
        class BadParserCommand(Command):

            def __init__(self, _parser):
                with test.assertRaises(AttributeError):
                    self.parser = None

            def __call__(self):
                with test.assertRaises(AttributeError):
                    self.parser = None

        test.try_main(BadParserCommand)


class TestSendCommandResult(TryCommandTestCase):

    def test_execution(self):
        class CarefulCommand(Local):

            def prepare(self_, args):
                # don't clutter test output
                args.foreground = False

                (code, std, err) = yield self_.local['which']['python']

                self.assertEqual(code, 0)
                self.assertTrue(std)
                self.assertFalse(err)

                (code, std, err) = yield self_.local['which']['TOTAL-FAKE']

                self.assertEqual(code, 1)
                self.assertFalse(std)
                self.assertFalse(err)

            prepare.retcode = None

        self.try_command(CarefulCommand)

    def test_dry_run(self):
        class SmartCommand(Local):

            def prepare(self_, args):
                args.execute_commands = False

                (code, std, err) = yield self_.local['which']['python']

                self.assertIsNone(code)
                self.assertIsNone(std)
                self.assertIsNone(err)

                (code, std, err) = yield self_.local['which']['TOTAL-FAKE']

                self.assertIsNone(code)
                self.assertIsNone(std)
                self.assertIsNone(err)

        with mock.patch('sys.stdout', new=io.StringIO()) as output:
            self.try_command(SmartCommand)

        plain_output = ANSI_ESCAPE.sub('', output.getvalue())
        self.assertEqual(
            plain_output,
            '> /usr/bin/which python\n'
            '> /usr/bin/which TOTAL-FAKE\n'
        )

    def test_non_gen(self):
        command = mock.Mock(spec=Local.local['which']['python'])

        class SimpleCommand(Local):

            def prepare(self_, args):
                # mock not configured to handle foreground operation
                args.foreground = False
                return command

        self.try_command(SimpleCommand)
        command.run.assert_called_once_with()


class TestThrowCommandException(TryCommandTestCase):

    def test_throw(self):
        class CarefulCommand(Local):

            def prepare(self_, args):
                # don't clutter test output
                args.foreground = False

                with self.assertRaises(self_.local.ProcessExecutionError):
                    yield self_.local['which']['TOTAL-FAKE']

        self.try_command(CarefulCommand)

    def test_naive(self):
        class NaiveCommand(Local):

            def prepare(self_, args):
                # don't clutter test output
                args.foreground = False

                yield self_.local['which']['TOTAL-FAKE']

        with self.assertRaises(NaiveCommand.local.ProcessExecutionError):
            self.try_command(NaiveCommand)

    def test_non_gen(self):
        class SimpleCommand(Local):

            def prepare(self_, args):
                # don't clutter test output
                args.foreground = False

                return self_.local['which']['TOTAL-FAKE']

        with self.assertRaises(SimpleCommand.local.ProcessExecutionError):
            self.try_command(SimpleCommand)


class TestCommandDecorator(unittest.TestCase):

    @staticmethod
    def command():
        pass

    def test_vanilla_cmd(self):
        command = cmd(self.command)
        self.assertIsNot(command, self.command)
        self.assertIs(command.__call__, self.command)
        self.assertTrue(issubclass(command, GeneratedCommand))
        self.assertTrue(issubclass(command, Command))
        self.assertEqual(command._parser_args_, [])
        self.assertIs(command(None).__call__, self.command)

    def test_parsing_cmd(self):
        parser_args0 = ('-1',)
        parser_kwargs0 = {
            'action': 'store_const',
            'const': '\n',
            'default': ' ',
            'dest': 'sep',
            'help': 'list one file per line',
        }
        parser_args1 = ('-h', '--human-readable')
        parser_kwargs1 = {
            'action': 'store_true',
            'dest': 'human',
            'help': 'print human readable sizes (e.g., 1K 234M 2G)',
        }

        command = cmd(*parser_args0, **parser_kwargs0)(
            cmd(*parser_args1, **parser_kwargs1)(
                self.command
            )
        )
        self.assertIsNot(command, self.command)
        self.assertIs(command.__call__, self.command)
        self.assertTrue(issubclass(command, GeneratedCommand))
        self.assertTrue(issubclass(command, Command))
        self.assertEqual(command._parser_args_, [(parser_args1, parser_kwargs1),
                                                 (parser_args0, parser_kwargs0)])

        parser = mock.Mock()
        instance = command(parser)
        self.assertEqual(parser.add_argument.call_count, 2)
        parser.add_argument.assert_has_calls([(parser_args1, parser_kwargs1),
                                              (parser_args0, parser_kwargs0)])
        self.assertIs(instance.__call__, self.command)

    def test_local_cmd(self):
        command = local(self.command)
        self.assertIsNot(command, self.command)
        self.assertIs(command.prepare, self.command)
        self.assertTrue(issubclass(command, GeneratedCommand))
        self.assertTrue(issubclass(command, Local))
        self.assertEqual(command._parser_args_, [])

        instance = command(None)
        self.assertIsInstance(instance.prepare, types.MethodType)
        self.assertIs(instance.prepare.__func__, self.command)

    def test_local_method(self):
        command = localmethod(self.command)
        self.assertIsNot(command, self.command)
        self.assertIsInstance(command.prepare, CommandMethod)
        self.assertIs(command.prepare.__func__, self.command)
        self.assertTrue(issubclass(command, GeneratedCommand))
        self.assertTrue(issubclass(command, Local))
        self.assertEqual(command._parser_args_, [])

        instance = command(None)
        instance.__getitem__ = mock.Mock()
        self.assertIsInstance(instance.prepare, types.MethodType)
        self.assertIs(instance.prepare.__func__, self.command)
        instance.__getitem__.assert_has_calls(2 * [mock.call((-1,))])


class TestLocalModifier(TryCommandTestCase):

    def test_single_default(self):
        # tough to trick TEE's select.select() with anything but actual
        # file descriptors; so, we'll provide them (as TemporaryFile).

        with tempfile.TemporaryFile() as stdout, \
             tempfile.TemporaryFile() as stderr:

            process = mock.Mock(stdout=stdout,
                                stderr=stderr)
            manager = mock.MagicMock()
            command = mock.Mock(spec=Local.local['which']['python'])
            command.bgrun.return_value = manager
            manager.__enter__.return_value = process

            class SimpleCommand(Local):

                def prepare(_self):
                    return command

            self.try_command(SimpleCommand)

        command.bgrun.assert_called_once_with(
            retcode=0,
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=None,
        )
        process.poll.assert_called_once_with()

    def test_single_foreground(self):
        command = mock.Mock(spec=Local.local['which']['python'])

        class SimpleCommand(Local):

            def prepare(self_):
                return (self_.local.FG, command)

        self.try_command(SimpleCommand)
        command.assert_called_once_with(
            retcode=0,
            stderr=None,
            stdin=None,
            stdout=None,
            timeout=None,
        )

    def test_generator_background(self):
        command = mock.Mock(spec=Local.local['which']['python'])

        class SimpleCommand(Local):

            def prepare(self_):
                result = yield (self_.local.BG, command)
                self.assertIsInstance(result, plumbum.commands.Future)
                self.assertIs(result.proc, command.popen.return_value)

        self.try_command(SimpleCommand)
        command.popen.assert_called_once_with()

    def test_simple_shh(self):
        command = mock.Mock(spec=Local.local['which']['python'])

        class SimpleCommand(Local):

            def prepare(self_):
                return (self_.local.SHH, command)

        self.try_command(SimpleCommand)
        command.run.assert_called_once_with(
            retcode=0,
            timeout=None,
        )

    def test_global_params(self):
        command = mock.Mock(spec=Local.local['which']['pythoX'])

        class SimpleCommand(Local):

            def prepare(self_):
                return (self_.local.FG, command)

            prepare.retcode = None

        self.try_command(SimpleCommand)
        command.assert_called_once_with(
            retcode=None,
            stderr=None,
            stdin=None,
            stdout=None,
            timeout=None,
        )

    def test_modifier_params(self):
        command = mock.Mock(spec=Local.local['which']['pythoX'])

        class SimpleCommand(Local):

            def prepare(self_):
                return (self_.local.FG(retcode=None), command)

        self.try_command(SimpleCommand)
        command.assert_called_once_with(
            retcode=None,
            stderr=None,
            stdin=None,
            stdout=None,
            timeout=None,
        )


class TryExecuteTestCase(unittest.TestCase):

    test_target = None

    @classmethod
    def declare_success(cls):
        cls.test_target = 'SUCCESS'

    @classmethod
    def clear_success(cls):
        cls.test_target = None

    def tearDown(self):
        try:
            del sys.modules['manage']
        except KeyError:
            pass

        self.clear_success()

    def try_execute(self, argv=None):
        if argv is None:
            argv = []

        argv.append(self.__class__.__name__)

        try:
            execute(argv=argv)
        except SystemExit as exc:
            self.fail(exc)


class TestExecutePath(TryExecuteTestCase):

    def test_module(self):
        self.try_execute([
            '--manage-file', os.path.join(DATA_DIR, 'execute_1', 'manage.py'),
        ])
        self.assertEqual(self.test_target, 'SUCCESS')

    def test_package(self):
        self.try_execute([
            '--manage-file', os.path.join(DATA_DIR, 'execute_2', 'manage'),
            'subcommand',
        ])
        self.assertEqual(self.test_target, 'SUCCESS')


class TryExecuteCwdTestCase(TryExecuteTestCase):

    sample_path = None

    def setUp(self):
        self.cwd0 = os.getcwd()
        os.chdir(self.sample_path)

        # CWD is usually *not* on PYTHONPATH
        try:
            self.cwd_path_index = sys.path.index('')
        except ValueError:
            self.cwd_on_path = False
            self.cwd_path_index = None
        else:
            self.cwd_on_path = True
            sys.path.remove('')

    def tearDown(self):
        os.chdir(self.cwd0)

        if self.cwd_on_path:
            if sys.path[self.cwd_path_index] != '':
                sys.path.insert(self.cwd_path_index, '')
        elif self.cwd_path_index is not None:
            if sys.path[self.cwd_path_index] == '':
                del sys.path[self.cwd_path_index]

        super().tearDown()


class TestExecuteFile(TryExecuteCwdTestCase):

    sample_path = os.path.join(DATA_DIR, 'execute_1')

    def test_on_pythonpath(self):
        if self.cwd_path_index is None:
            self.cwd_path_index = 0

        sys.path.insert(self.cwd_path_index, '')

        self.try_execute()
        self.assertEqual(self.test_target, 'SUCCESS')

    @unittest.skipIf(sys.version_info >= (3, 7), "inapplicable to python3.7 and higher")
    def test_not_on_pythonpath(self):
        with self.assertRaises(ImportError):
            import manage  # noqa: F401

        self.try_execute()
        self.assertEqual(self.test_target, 'SUCCESS')


class TestExecutePackage(TryExecuteCwdTestCase):

    sample_path = os.path.join(DATA_DIR, 'execute_2')

    def test_on_pythonpath(self):
        if self.cwd_path_index is None:
            self.cwd_path_index = 0

        sys.path.insert(self.cwd_path_index, '')

        self.try_execute(['subcommand'])
        self.assertEqual(self.test_target, 'SUCCESS')

    @unittest.skipIf(sys.version_info >= (3, 7), "inapplicable to python3.7 and higher")
    def test_not_on_pythonpath(self):
        with self.assertRaises(ImportError):
            import manage  # noqa: F401

        self.try_execute(['subcommand'])
        self.assertEqual(self.test_target, 'SUCCESS')


if __name__ == '__main__':
    unittest.main()
