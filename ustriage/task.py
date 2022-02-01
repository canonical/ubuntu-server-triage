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
        }[self.obj.target.resource_type_link]
        return ' '.join(self.title.split(' ')[start_field:]).replace('"', '')

    def get_flags(self):
        """Get flags representing the status of the task."""
        flags = ''
        flags += '*' if self.subscribed else ' '
        flags += '+' if self.last_activity_ours else ' '
        if (self.AGE and self.date_last_updated > self.AGE):
            flags += 'U'
        else:
            flags += ' '
        return flags

    def compose_pretty(self, shortlinks=True, extended=False):
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

        flags = self.get_flags()

        text = '%s - %3s %-13s %-19s' % (
            bug_url,
            flags,
            ('%s' % self.status),
            ('[%s]' % truncate_string(self.src, 16))
        )
        if extended:
            text += ' %8s %-10s %-13s' % (
                self.date_last_updated.strftime('%d.%m.%y'),
                self.importance,
                ('' if not self.assignee
                 else '=> %s' % truncate_string(self.assignee, 9))
            )
        text += ' - %s' % truncate_string(self.short_title, 60)
        return text

    def compose_dup(self, shortlinks=True, extended=False):
        """Compose a printable line of reduced information for a dup."""
        if shortlinks:
            duplen = str(self.BUG_NUMBER_LENGTH + len(self.SHORTLINK_ROOT))
        else:
            duplen = str(self.BUG_NUMBER_LENGTH + len(self.LONG_URL_ROOT))
        format_string = ('%-' + duplen + 's')
        dupprefix = format_string % 'also:'

        flags = self.get_flags()

        text = '%s - %3s %-13s %-19s' % (
            dupprefix,
            flags,
            ('%s' % self.status),
            ('[%s]' % truncate_string(self.src, 16))
        )
        if extended:
            text += ' %8s %-10s %-13s' % (
                "",
                self.importance,
                ('' if not self.assignee
                 else '=> %s' % truncate_string(self.assignee, 9))
            )
        return text

    def sort_key(self):
        """Sort method."""
        return (not self.last_activity_ours, self.number, self.src)

    def sort_date(self):
        """Sort by date."""
        return self.date_last_updated
