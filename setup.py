"""setup.py"""
from setuptools import setup

setup(name='ustriage',
      version='1.0',
      description='Output Ubuntu Server Launchpad bugs for triage',
      author='Joshua Powers',
      author_email='josh.powers@canonical.com',
      url='https://github.com/powersj/ubuntu-server-triage',
      download_url=('https://github.com/powersj/ubuntu-server-triage/' +
                    'tarball/master'),
      keywords=['ubuntu', 'launchpad', 'triage', 'bugs'],
      license='GNU General Public License v3 or later',
      classifiers=[
          "Development Status :: 5 - Production/Stable",
          "Environment :: Console",
          "Intended Audience :: Developers",
          "License :: OSI Approved :: GNU General Public License v3 or later"
          " (GPLv3+)",
          "Natural Language :: English",
          "Operating System :: POSIX :: Linux",
          "Programming Language :: Python :: 3 :: Only",
          "Programming Language :: Python :: 3.5",
          "Topic :: Software Development :: Quality Assurance",
          "Topic :: Software Development :: Testing",
      ],
      entry_points={
          'console_scripts': ['ustriage=ustriage.py:main']
      },
      install_requires=[],
      zip_safe=False
     )
