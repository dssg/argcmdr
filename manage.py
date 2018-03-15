"""argcmdr's own management module"""
from argcmdr import Local


class Manage(Local):
    """manage development of argcmdr ... (with argcmdr)"""

    class Test(Local):
        """run tests"""

        def prepare(self):
            return self.local['tox']

    class Build(Local):
        """build package"""

        def prepare(self):
            return self.local['python'][
                'setup.py',
                'sdist',
                'bdist_wheel',
            ]
