"""Task object for server triage script.

This encapsulates a launchpadlib Task object, caches some queries,
stores some other properties (eg. the team-"subscribed"-ness) as needed
by callers, and presents a bunch of derived properties. All Task property
specific handling is encapsulated here.

Copyright 2017-2018 Canonical Ltd.
Joshua Powers <josh.powers@canonical.com>
"""

from functools import lru_cache


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


def truncate_string(text, length=20):
    """Truncate string and hint visually if truncated."""
    str_text = str(text)
    truncated = str_text[0:length]
    if len(str_text) > length:
        truncated = truncated[:-1] + '…'
    return truncated


class Task:
    """Our representation of a Launchpad task."""

    LONG_URL_ROOT = 'https://pad.lv/'
    SHORTLINK_ROOT = 'LP: #'
    BUG_NUMBER_LENGTH = 7
    AGE = None
    OLD = None

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

    def get_releases(self, open_bug_statuses):
        """List of chars reflecting per release status.

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
            release_char = task_elements[5][0]
            if release_char == '+':
                release_char = "d"

            # report closed tasks as upper case
            if task.status in open_bug_statuses:
                release_info += release_char
            else:
                release_info += release_char.upper()

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
            flags += 'v'
        else:
            flags += ' '
        if any('verification-done-' in tag for tag in self.tags):
            flags += 'V'
        else:
            flags += ' '
        return flags

    def compose_pretty(self, shortlinks=True, extended=False, newbug=False,
                       open_bug_statuses=None):
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
            self.get_releases(open_bug_statuses),
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
