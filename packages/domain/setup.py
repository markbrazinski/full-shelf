from setuptools import setup, find_packages

setup(
    name="full-shelf-domain",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.0.0",
        "typing-extensions>=4.5.0",
    ],
)
