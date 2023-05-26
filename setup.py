from setuptools import setup


def get_requirements():
    with open('requirements.txt') as f:
        requirements = f.read().splitlines()
    return requirements


setup(
    name='mlb-statsapi',
    version='1.0.1',
    packages=['mlb_statsapi'],
    url='',
    license='',
    author='',
    author_email='',
    description="Wrapper to access stats API data from MLB",
    classifiers=[],
    install_requires=get_requirements(),
    entry_points={}
)