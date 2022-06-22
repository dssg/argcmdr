import re
from pathlib import Path
from setuptools import setup

MODULE = 'argcmdr'
MODULE_FILE = MODULE + '.py'
SRC_DIR = 'src'
MODULE_PATH = Path(__file__).parent / SRC_DIR / MODULE_FILE
README_PATH = Path(__file__).parent / 'README.rst'
VERSION = re.search(
    r'''^__version__ *= *["']([.\d]+)["']$''',
    MODULE_PATH.read_text(),
    re.M,
).group(1)

setup(
    name=MODULE,
    version=VERSION,
    description="Thin argparse wrapper for quick, clear and easy "
                "declaration of hierarchical console command interfaces",
    long_description=README_PATH.read_text(),
    author="Center for Data Science and Public Policy",
    author_email='datascifellows@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
    ],
    url="https://github.com/dssg/argcmdr",
    python_requires='>=3.6',
    package_dir={'': SRC_DIR},
    py_modules=[MODULE],
    install_requires=[
        'argcomplete==1.9.4',
        'Dickens==1.0.1',

        # Provisionally using fork of plumbum at:
        #
        #     https://github.com/jesteria/plumbum/tree/v1.7.2-604
        #
        # so as to include patch:
        #
        #     https://github.com/jesteria/plumbum/commit/674ae03927ef05f6a2e873019ae0f68231737eb8
        #
        # until issue #604 is resolved:
        #
        #     https://github.com/tomerfiliba/plumbum/issues/604
        #
        # For now not:
        #
        # 'plumbum==1.7.2',
        #
        # Provisionally:
        #
        'plumbum @ git+https://github.com/jesteria/plumbum.git@v1.7.2-604',
    ],
    entry_points={
        'console_scripts': [
            'manage = argcmdr:execute',
        ],
    },
)
