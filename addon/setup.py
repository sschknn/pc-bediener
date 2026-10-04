"""Setup für das PC-Bediener + FL Studio OpenCode-Addon."""

from setuptools import setup, find_packages

setup(
    name="pcbediener-addon",
    version="1.0.0",
    description="OpenCode-Addon für PC-Bediener und FL Studio Produktion",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Frank",
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "pcbediener",
        "mcp",
    ],
    python_requires=">=3.11",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
    ],
)
