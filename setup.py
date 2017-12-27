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
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
    ],
    url="https://github.com/dssg/argcmdr",
    package_dir={'': SRC_DIR},
    py_modules=[MODULE],
    install_requires=[
        'Dickens==1.0.1',
        'plumbum==1.6.4',
    ],
)
