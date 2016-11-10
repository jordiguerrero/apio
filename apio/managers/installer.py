# -*- coding: utf-8 -*-
# -- This file is part of the Apio project
# -- (C) 2016 FPGAwars
# -- Author Jesús Arroyo
# -- Licence GPLv2

import re
import click
import shutil

from os import makedirs, remove, rename
from os.path import isfile, isdir, join, basename

from apio.util import get_home_dir, get_systype
from apio.api import api_request
from apio.resources import Resources
from apio.profile import Profile

from apio.managers.downloader import FileDownloader
from apio.managers.unpacker import FileUnpacker


class Installer(object):

    def __init__(self, package, platform=''):

        # Parse version
        if '@' in package:
            split = package.split('@')
            self.package = split[0]
            self.version = split[1]
        else:
            self.package = package
            self.version = None

        self.forced_install = False
        self.valid_version = True

        self.packages_dir = None

        self.resources = Resources()

        if self.package in self.resources.packages:

            self.profile = Profile()

            data = self.resources.packages[self.package]

            if self.version:
                # Validate version
                valid = self._validate_version(
                    data['repository']['name'],
                    data['repository']['organization'],
                    data['release']['tag_name'],
                    self.version
                )
                if valid:
                    self.forced_install = True
                else:
                    self.valid_version = False
            else:
                # Get latest version
                self.version = self._get_latest_version(
                    data['repository']['name'],
                    data['repository']['organization'],
                    data['release']['tag_name']
                )

            self.platform = platform if platform else self._get_platform()

            release = data['release']
            self.compressed_name = release['compressed_name'].replace(
                '%V', self.version).replace('%P', self.platform)
            self.uncompressed_name = release['uncompressed_name'].replace(
                '%V', self.version).replace('%P', self.platform)
            self.package_name = data['release']['package_name']

            if isinstance(data['release']['extension'], dict):
                for os in ['linux', 'darwin', 'windows']:
                    if os in self.platform:
                        self.extension = data['release']['extension'][os]
            else:
                self.extension = data['release']['extension']

            self.tarball = self._get_tarball_name(
                self.compressed_name,
                self.extension
            )

            self.download_url = self._get_download_url(
                data['repository']['name'],
                data['repository']['organization'],
                data['release']['tag_name'].replace('%V', self.version),
                self.tarball
            )

            dirname = 'packages'
            if platform:
                self.packages_dir = join('.', dirname)
                self.forced_install = True
            else:
                self.packages_dir = join(get_home_dir(), dirname)

    def install(self):
        if self.packages_dir is None or self.version is None:
            click.secho(
                'Error: No such package \'{0}\''.format(self.package),
                fg='red')
        elif not self.valid_version:
            click.secho(
                'Error: package \'{0}\' has no version {1}'.format(
                    self.package, self.version),
                fg='red')
        else:
            click.echo('Installing %s package:' % click.style(
                self.package, fg='cyan'))
            if not isdir(self.packages_dir):
                makedirs(self.packages_dir)
            assert isdir(self.packages_dir)
            try:
                dlpath = None
                dlpath = self._download(self.download_url)
                if dlpath:
                    package_dir = join(self.packages_dir, self.package)
                    if isdir(package_dir):
                        shutil.rmtree(package_dir)
                    if self.uncompressed_name:
                        self._unpack(dlpath, self.packages_dir)
                    else:
                        self._unpack(dlpath, join(
                            self.packages_dir, self.package_name))
            except Exception as e:
                click.secho('Error: ' + str(e), fg='red')
            else:
                if dlpath:
                    remove(dlpath)
                    self.profile.add_package(self.package, self.version)
                    self.profile.save()
                    click.secho(
                        """Package \'{}\' has been """
                        """successfully installed!""".format(self.package),
                        fg='green')

            # Rename unpacked dir to package dir
            if self.uncompressed_name:
                unpack_dir = join(self.packages_dir, self.uncompressed_name)
                package_dir = join(self.packages_dir, self.package_name)
                if isdir(unpack_dir):
                    rename(unpack_dir, package_dir)

    def uninstall(self):
        if self.version is None:
            click.secho(
                'Error: No such package \'{0}\''.format(self.package),
                fg='red')
        else:
            if isdir(join(self.packages_dir, self.package_name)):
                click.echo('Uninstalling %s package' % click.style(
                    self.package, fg='cyan'))
                shutil.rmtree(join(self.packages_dir, self.package_name))
                click.secho(
                    """Package \'{}\' has been """
                    """successfully uninstalled!""".format(self.package),
                    fg='green')
            else:
                click.secho('Package \'{0}\' is not installed'.format(
                    self.package), fg='red')
            self.profile.remove_package(self.package)
            self.profile.save()

    def _get_platform(self):
        return get_systype()

    def _get_download_url(self, name, organization, tag, tarball):
        url = 'https://github.com/{0}/{1}/releases/download/{2}/{3}'.format(
            organization,
            name,
            tag,
            tarball)
        return url

    def _get_tarball_name(self, name, extension):
        tarball = '{0}.{1}'.format(
            name,
            extension)
        return tarball

    def _validate_version(self, name, organization, tag_name, version):
        releases = api_request('{}/releases'.format(name), organization)
        if releases is not None:
            for release in releases:
                if 'tag_name' in release and \
                   release['tag_name'] == tag_name.replace('%V', version):
                    return True
        return False

    def _get_latest_version(self, name, organization, tag_name):
        version = ''
        latest_release = api_request(
            '{}/releases/latest'.format(name), organization)
        if latest_release is not None and 'tag_name' in latest_release:
            pattern = tag_name.replace('%V', '(?P<v>.*?)') + '$'
            match = re.search(pattern, latest_release['tag_name'])
            if match:
                version = match.group('v')
        return version

    def _download(self, url):
        # Note: here we check only for the version of locally installed
        # packages. For this reason we don't say what's the installation
        # path.
        if self.profile.check_package_version(self.package, self.version) \
           or self.forced_install:
            fd = FileDownloader(url, self.packages_dir)
            filepath = fd.get_filepath()
            click.secho('Download ' + basename(filepath))
            try:
                fd.start()
            except KeyboardInterrupt:
                if isfile(filepath):
                    remove(filepath)
                click.secho('Abort download!', fg='red')
                exit(1)
            return filepath
        else:
            click.secho('Already installed. Version {0}'.format(
                self.profile.get_package_version(self.package)), fg='yellow')
            return None

    def _unpack(self, pkgpath, pkgdir):
        fu = FileUnpacker(pkgpath, pkgdir)
        return fu.start()
