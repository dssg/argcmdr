import argparse
import io
import unittest
from unittest import mock

from argcmdr import *
from argcmdr import exhaust_iterable


class TryCommandTestCase(unittest.TestCase):

    def try_command(self, command_cls):
        # ensure parser is available to tests with nested command defns
        self.parser = command_cls.base_parser()

        command = command_cls(self.parser)
        self.parser.set_defaults(
            __command__=command,
            __parser__=self.parser,
        )

        args = self.parser.parse_args([])
        command(args)


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


if __name__ == '__main__':
    unittest.main()
