#!/usr/bin/env python3
"""Setup script for localRAGcoder — pip-installable package.

Version: 1.0.0
"""

from setuptools import setup, find_packages

setup(
    name="localRAGcoder",
    version="1.0.0",
    description="Local RAG Knowledge Graph Engine for OpenCode IDE",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="localRAGcoder Team",
    license="MIT",
    packages=find_packages(include=["engine", "engine.*"]),
    python_requires=">=3.11",
    install_requires=["kuzu>=0.7.0"],
    extras_require={
        "dev": ["pytest"],
    },
    entry_points={
        "console_scripts": [
            "lrag=engine.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
