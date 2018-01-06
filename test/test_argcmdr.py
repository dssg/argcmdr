import unittest

from argcmdr import *
from argcmdr import exhaust_iterable


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
        (_parser, self.root) = next(interface)
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
        for (_parser, command) in self.Root.build_interface():
            setattr(self, command.name, command)

    def test_root_0(self):
        self.assertIsNone(self.root.root)

    def test_root_1(self):
        self.assertIs(self.branch.root, self.root)

    def test_root_2(self):
        self.assertIs(self.leaf.root, self.root)


if __name__ == '__main__':
    unittest.main()
