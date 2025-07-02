# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name='pynetft',
    version='1.0.3',
    author='Xudong Han',
    description='Python library for reading data from ATI Force/Torque sensors with Net F/T interface',
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url='https://github.com/han-xudong/pyNetFT',
    packages=find_packages(),
    python_requires='>=3.6',
    keywords=['Net F/T', 'sensor'],
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.10',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)