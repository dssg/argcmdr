import argparse
import io
import os
import pdb
import subprocess
import types
import unittest
import sys
import traceback
from unittest import mock

import plumbum.commands

import argcmdr
from argcmdr import *
from argcmdr import CommandMethod, GeneratedCommand, exhaust_iterable


TEST_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(TEST_DIR, 'data')


def pm():
    info = sys.exc_info()
    traceback.print_exception(*info)
    pdb.post_mortem(info[2])


class TryCommandTestCase(unittest.TestCase):

    def try_command(self, command_cls):
        # ensure parser is available to tests with nested command defns
        (self.parser, args) = command_cls.get_parser()
        self.parser.parse_args([], args)
        command = args.__command__
        command.call(args)


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
        interface = self.Root.build_interface()
        (_parser, _namespace, self.root) = next(interface)
        exhaust_iterable(interface)

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
        for (_parser, _namespace, command) in self.Root.build_interface():
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
                self.assertIs(args.__command__, self_)
                self.assertIs(args.__parser__, self.parser)

        self.try_command(Simple)

    def test_deep(self):
        class Deep(Local):

            def prepare(self_, args, parser):
                self.assertIsInstance(self_, Deep)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args.__command__, self_)
                self.assertIs(args.__parser__, self.parser)
                self.assertIs(parser, self.parser)

        self.try_command(Deep)

    def test_fancy(self):
        class Fancy(Local):

            def prepare(self_, args, parser, lang='en'):
                self.assertIsInstance(self_, Fancy)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args.__command__, self_)
                self.assertIs(args.__parser__, self.parser)
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

            def prepare(self_, args, parser, lang):
                self.fail("how did this happen?")

        with self.assertRaises(TypeError) as context:
            self.try_command(Bad)

        exc = context.exception
        self.assertIsInstance(exc, TypeError)
        self.assertEqual(exc.args, ("Bad.prepare() requires too many "
                                    "positional arguments: 'lang'",))

    def test_tricky(self):
        class Tricky(Local):

            def prepare(self_, args, parser=None, lang='en'):
                self.assertIsInstance(self_, Tricky)
                self.assertIsInstance(args, argparse.Namespace)
                self.assertIs(args.__command__, self_)
                self.assertIs(args.__parser__, self.parser)
                self.assertIs(parser, self.parser)
                self.assertEqual(lang, 'en')

        self.try_command(Tricky)


class TestArgsProperty(TryMainTestCase):

    def test_identity(self):
        class ArgsCommand(Command):

            def __call__(self_, args):
                self.assertIs(self_.args, args)

        self.try_main(ArgsCommand)

    def test_error(self):
        class BadArgsCommand(Command):

            def __init__(self_, _parser):
                with self.assertRaises(RuntimeError):
                    self_.args

            def __call__(self):
                pass

        self.try_main(BadArgsCommand)


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

                # don't clutter test output
                args.show_commands = False

                (code, std, err) = yield self_.local['which']['python']

                self.assertIsNone(code)
                self.assertIsNone(std)
                self.assertIsNone(err)

                (code, std, err) = yield self_.local['which']['TOTAL-FAKE']

                self.assertIsNone(code)
                self.assertIsNone(std)
                self.assertIsNone(err)

        self.try_command(SmartCommand)

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
        self.assertEqual(command._args_, [])
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
                  self.command))
        self.assertIsNot(command, self.command)
        self.assertIs(command.__call__, self.command)
        self.assertTrue(issubclass(command, GeneratedCommand))
        self.assertTrue(issubclass(command, Command))
        self.assertEqual(command._args_, [(parser_args1, parser_kwargs1),
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
        self.assertEqual(command._args_, [])

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
        self.assertEqual(command._args_, [])

        instance = command(None)
        instance.__getitem__ = mock.Mock()
        self.assertIsInstance(instance.prepare, types.MethodType)
        self.assertIs(instance.prepare.__func__, self.command)
        instance.__getitem__.assert_has_calls(2 * [mock.call((-1,))])


class TestLocalModifier(TryCommandTestCase):

    def test_single_default(self):
        process = mock.Mock()
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
            argcmdr.execute(argv=argv)
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
        self.cwd_path_index = sys.path.index('')
        sys.path.remove('')

    def tearDown(self):
        os.chdir(self.cwd0)

        if sys.path[self.cwd_path_index] != '':
            sys.path.insert(self.cwd_path_index, '')

        super().tearDown()


class TestExecuteFile(TryExecuteCwdTestCase):

    sample_path = os.path.join(DATA_DIR, 'execute_1')

    def test_on_pythonpath(self):
        sys.path.insert(self.cwd_path_index, '')

        self.try_execute()
        self.assertEqual(self.test_target, 'SUCCESS')

    def test_not_on_pythonpath(self):
        with self.assertRaises(ImportError):
            import manage

        self.try_execute()
        self.assertEqual(self.test_target, 'SUCCESS')


class TestExecutePackage(TryExecuteCwdTestCase):

    sample_path = os.path.join(DATA_DIR, 'execute_2')

    def test_on_pythonpath(self):
        sys.path.insert(self.cwd_path_index, '')

        self.try_execute(['subcommand'])
        self.assertEqual(self.test_target, 'SUCCESS')

    def test_not_on_pythonpath(self):
        with self.assertRaises(ImportError):
            import manage

        self.try_execute(['subcommand'])
        self.assertEqual(self.test_target, 'SUCCESS')


if __name__ == '__main__':
    unittest.main()
