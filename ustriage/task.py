"""Task object for server triage script.

This encapsulates a launchpadlib Task object, caches some queries,
stores some other properties (eg. the team-"subscribed"-ness) as needed
by callers, and presents a bunch of derived properties. All Task property
specific handling is encapsulated here.

Copyright 2017-2018 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""

import itertools
import re
import urllib

from functools import lru_cache

import debian.deb822

DISTRIBUTION_RESOURCE_TYPE_LINK = (
    'https://api.launchpad.net/devel/#distribution'
)

DISTRIBUTION_SOURCE_PACKAGE_RESOURCE_TYPE_LINK = (
    'https://api.launchpad.net/devel/#distribution_source_package'
)

SOURCE_PACKAGE_RESOURCE_TYPE_LINK = (
    'https://api.launchpad.net/devel/#source_package'
)

PROJECT_RESOURCE_TYPE_LINK = (
    'https://api.launchpad.net/devel/#project'
)

# We used to use red, but the contrast black/dark-red is video encoded badly
COLOR_CYAN = "\033[0;36m"
COLOR_GREEN = "\033[0;32m"
COLOR_YELLOW = "\033[0;33m"
COLOR_RESET = '\033[0m'


def truncate_string(text, length=20):
    """Truncate string and hint visually if truncated."""
    str_text = str(text)
    truncated = str_text[0:length]
    if len(str_text) > length:
        truncated = truncated[:-1] + '…'
    return truncated


def mark(text, color):
    """Mark text with the specified color."""
    return color + text + COLOR_RESET


def find_changes_bugs(changes_url):
    """Return the list of bugs affected by a change URL."""
    with urllib.request.urlopen(changes_url) as changes_fobj:
        changes = debian.deb822.Changes(changes_fobj)
    try:
        bugs_str = changes["Launchpad-Bugs-Fixed"]
    except KeyError:
        return []
    return bugs_str.split()


def get_upload_source_urls(upload):
    """Get source URLs for an upload."""
    if upload.contains_source:
        return upload.sourceFileUrls()

    if upload.contains_copy:
        try:
            copy_source_archive = upload.copy_source_archive
            # Trigger a problem ValueError exception now rather than later
            # This is magic launchpadlib behaviour: accessing an attribute
            # of copy_source_archive may fail later on an access permission
            # issue due to lazy loading.
            getattr(copy_source_archive, "self_link")
        except ValueError as err:
            raise RuntimeError(
                f"EPERM: {upload} copy_source_archive attribute"
            ) from err
        return next(
            iter(
                upload.copy_source_archive.getPublishedSources(
                    source_name=upload.package_name,
                    version=upload.package_version,
                    exact_match=True,
                    order_by_date=True,
                )
            )
        ).sourceFileUrls()
    raise RuntimeError(f"Cannot find source for {upload}")


class Task:
    """Our representation of a Launchpad task."""

    LONG_URL_ROOT = 'https://pad.lv/'
    SHORTLINK_ROOT = 'LP: #'
    BUG_NUMBER_LENGTH = 7
    AGE = None
    OLD = None
    LP = None
    NOWORK_BUG_STATUSES = []
    OPEN_BUG_STATUSES = []

    def __init__(self):
        """Init task object."""
        # Whether the team is subscribed to the bug
        self.subscribed = None
        # Whether the last activity was by us
        self.last_activity_ours = None
        self.obj = None

    @staticmethod
    def create_from_launchpadlib_object(obj, **kwargs):
        """Create object from launchpadlib."""
        self = Task()
        self.obj = obj
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    @staticmethod
    def get_header(extended=False):
        """Return a header matching the compose_pretty output."""
        text = '%-12s | %-6s | %-7s | %-13s | %-19s |' % (
            "Bug",
            "Flags",
            "Release",
            "Status",
            "Package")
        if extended:
            text += ' %-8s | %-10s | %-13s |' % (
                "Last Upd",
                "Prio",
                "Assignee"
            )
        text += ' %-70s |' % "Title"
        return text

    @property
    def url(self):
        """User-facing URL of the task."""
        return self.LONG_URL_ROOT + self.number

    @property
    def shortlink(self):
        """User-facing "shortlink" that gnome-terminal will autolink."""
        return self.SHORTLINK_ROOT + self.number

    @property
    @lru_cache()
    def number(self):
        """Bug number as a string."""
        # This could be str(self.obj.bug.id) but using self.title is
        # significantly faster
        return self.title.split(' ')[1].replace('#', '')

    @property
    @lru_cache()
    def tags(self):
        """List of the Bugs tags."""
        return self.obj.bug.tags

    @property
    @lru_cache()
    def date_last_updated(self):
        """Last update as datetime returned by launchpad."""
        return self.obj.bug.date_last_updated

    @property
    @lru_cache()
    def importance(self):
        """Return importance as returned by launchpad."""
        return self.obj.importance

    @property
    @lru_cache()
    def src(self):
        """Source package."""
        # This could be self.target.name but using self.title is
        # significantly faster
        return self.title.split(' ')[3]

    @property
    @lru_cache()
    def title(self):
        """Title as returned by launchpadlib."""
        return self.obj.title

    @property
    @lru_cache()
    def assignee(self):
        """Assignee as string returned by launchpadlib."""
        # String like https://api.launchpad.net/devel/~ahasenack
        # getting OBJ via API to determine the name is much slower, the
        # username is enough and faster
        if self.obj.assignee_link:
            return self.obj.assignee_link.split('~')[1]
        return False

    @property
    @lru_cache()
    def status(self):
        """Status as returned by launchpadlib."""
        return self.obj.status

    @property
    @lru_cache()
    def short_title(self):
        """Bug summary."""
        # This could be self.obj.bug.title but using self.title is
        # significantly faster
        start_field = {
            DISTRIBUTION_RESOURCE_TYPE_LINK: 4,
            DISTRIBUTION_SOURCE_PACKAGE_RESOURCE_TYPE_LINK: 5,
            SOURCE_PACKAGE_RESOURCE_TYPE_LINK: 6,
            PROJECT_RESOURCE_TYPE_LINK: 7,
        }[self.obj.target.resource_type_link]
        return ' '.join(self.title.split(' ')[start_field:]).replace('"', '')

    def _is_in_unapproved(self, series):
        """Determine if this task is in a -unapproved for a series."""
        # Thanks to Rbasak for the code that inspired this
        ubuntu = Task.LP.distributions["ubuntu"]
        distro_seriess = [ubuntu.getSeries(name_or_version=series)]
        uploads = itertools.chain.from_iterable(
            distro_series.getPackageUploads(pocket="Proposed",
                                            status="Unapproved",
                                            exact_match=True,
                                            name=self.src)
            for distro_series in distro_seriess
        )
        for upload in uploads:
            try:
                get_upload_source_urls(upload)
            except RuntimeError:
                # Could not get source URLs
                continue
            if not upload.changes_file_url:
                # Could not find changes file
                continue

            bug_numbers = find_changes_bugs(upload.changes_file_url)
            if self.number in bug_numbers:
                return True

        return False

    def get_releases(self, length):
        """List of one status char per release, padded to printable length.

        Gets a list of chars, one per supported release that show if that task
        exists (present) and is open (lower case) or closed (upper case).

        Note: This has to stay a fixed length string to maintain the layout
        """
        release_info = ''

        # breaking the URL is faster than checking it all through API
        for task in self.obj.bug.bug_tasks:
            task_elements = str(task).split('/')
            # skip root element and other projects
            if task_elements[4] != 'ubuntu':
                continue
            # Only care for the task that we high-level report about
            if task_elements[-3] != str(self.src):
                continue

            # get first char of release (devel = d)
            series = task_elements[5]
            release_char = series[0]
            if release_char == '+':
                release_char = "d"
            release_char = release_char.upper()

            # report closed tasks as upper case
            if task.status in Task.NOWORK_BUG_STATUSES:
                release_char = mark(release_char, COLOR_GREEN)
            elif release_char not in 'dD' and self._is_in_unapproved(series):
                release_char = mark(release_char, COLOR_CYAN)
            elif task.status in Task.OPEN_BUG_STATUSES:
                release_char = mark(release_char, COLOR_YELLOW)
            # Remaining e.g. incomplete stay as-is

            release_info += release_char

        # Due to all the control chars we add, we need to printable to length
        printable = re.sub('[^A-Z]+', '', release_info, 0)
        p_len = len(printable)
        p_need = length - p_len
        if p_need > 0:
            release_info += ' '*p_need

        return release_info

    def get_flags(self, newbug=False):
        """Get flags representing the status of the task.

        Note: This has to stay a fixed length string to maintain the layout
        """
        flags = ''
        flags += '*' if self.subscribed else ' '
        flags += '+' if self.last_activity_ours else ' '
        if (self.AGE and self.date_last_updated > self.AGE):
            flags += 'U'
        elif (self.OLD and self.date_last_updated < self.OLD):
            flags += 'O'
        else:
            flags += ' '
        flags += 'N' if newbug else ' '
        if any('verification-needed-' in tag for tag in self.tags):
            flags += mark('v', COLOR_CYAN)
        else:
            flags += ' '
        if any('verification-done-' in tag for tag in self.tags):
            flags += mark('V', COLOR_GREEN)
        else:
            flags += ' '
        return flags

    def compose_pretty(self, shortlinks=True, extended=False, newbug=False):
        """Compose a printable line of relevant information."""
        if shortlinks:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.SHORTLINK_ROOT)) +
                's'
            )
            bug_url = format_string % self.shortlink
        else:
            format_string = (
                '%-' +
                str(self.BUG_NUMBER_LENGTH + len(self.LONG_URL_ROOT)) +
                's'
            )
            bug_url = format_string % self.url

        text = '%-12s | %6s | %-7s | %-13s | %-19s |' % (
            bug_url,
            self.get_flags(newbug),
            self.get_releases(6),
            ('%s' % self.status),
            ('%s' % truncate_string(self.src, 19))
        )
        if extended:
            text += ' %8s | %-10s | %-13s |' % (
                self.date_last_updated.strftime('%d.%m.%y'),
                self.importance,
                ('' if not self.assignee
                 else '%s' % truncate_string(self.assignee, 12))
            )
        text += ' %70s |' % truncate_string(self.short_title, 70)
        return text

    def compose_dup(self, extended=False):
        """Compose a printable line of reduced information for a dup."""
        text = '%s,%s' % (
            ('%s' % self.status),
            ('%s' % truncate_string(self.src, 16))
        )
        if extended and self.assignee:
            text += ",%s" % truncate_string(self.assignee, 9)
        return text

    def sort_key(self):
        """Sort method."""
        return (not self.last_activity_ours, self.number, self.src)

    def sort_date(self):
        """Sort by date."""
        return self.date_last_updated
