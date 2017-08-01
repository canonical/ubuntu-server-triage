# Ubuntu Server Triage

[![Build Status](https://travis-ci.org/powersj/ubuntu-server-triage.svg?branch=master)](https://travis-ci.org/powersj/ubuntu-server-triage) [![Snap Status](https://build.snapcraft.io/badge/powersj/ubuntu-server-triage.svg)](https://build.snapcraft.io/user/powersj/ubuntu-server-triage)

Output Ubuntu Server Launchpad bugs that for triage. The script is used by members of the Ubuntu Server team to determine what Launchpad bugs to review on a particular day or range of days. Giving us programmatic access to a set of bugs to look at. The older method was to look at [this page](https://bugs.launchpad.net/ubuntu/?field.searchtext=&orderby=-date_last_updated&search=Search&field.status%3Alist=NEW&field.status%3Alist=CONFIRMED&field.status%3Alist=TRIAGED&field.status%3Alist=INPROGRESS&field.status%3Alist=FIXCOMMITTED&field.status%3Alist=INCOMPLETE_WITH_RESPONSE&field.status%3Alist=INCOMPLETE_WITHOUT_RESPONSE&assignee_option=any&field.assignee=&field.bug_reporter=&field.bug_commenter=&field.subscriber=&field.structural_subscriber=ubuntu-server&field.component-empty-marker=1&field.tag=&field.tags_combinator=ANY&field.status_upstream-empty-marker=1&field.has_cve.used=&field.omit_dupes.used=&field.omit_dupes=on&field.affects_me.used=&field.has_no_package.used=&field.has_patch.used=&field.has_branches.used=&field.has_branches=on&field.has_no_branches.used=&field.has_no_branches=on&field.has_blueprints.used=&field.has_blueprints=on&field.has_no_blueprints.used=&field.has_no_blueprints=on) and manually find all the bugs corresponding to a particular bug.

The easiest way to obtain the script and keep it updated is to use the snap:
```
sudo snap install ustriage --classic
```

If using the snap is not possible, you can instead obtain and run it by:
```
wget https://raw.githubusercontent.com/powersj/ubuntu-server-triage/master/ustriage/ustriage.py
chmod +x ustriage.py 
# Running with no arguments will get previous day's bugs
./ustriage.py
```

## Dates
Dates must follow the format: `%Y-%m-%d` (e.g. 2016-11-30, 1999-05-22)

### Single Date Argument
If only one date is given then all the bugs on that one day will be found. For example, the following finds all bugs last modified on only the 10th of September:
```
./ustriage.py 2016-09-10
```

### Two Date Arguments
If two dates are given then all the bugs found on those days and between (fully inclusive) wil be found. For example, the following, finds all bugs last modified on the 10th, 11th, and 12th of September:
```
./ustriage.py 2016-09-10 2016-09-12
```

## Arguments
### Follow Bug Links
By default the script outputs links of the form "LP: #XXXXXX". Ubuntu's
default browser, gnome-terminal, makes these appear as hyperlinks
automatically, saving space and leaving more for the bug titles. If
instead you'd like full URLs, use `--fullurls`.

### Open Bugs in Browser
Quite commonly the triager wants to open all bugs in the browser, to read, review and manage them. Via ``open`` argument that can be done automatically.
```
./ustriage.py --open 2016-09-10 2016-09-12
```

### Launchpad Name and Subscription Type
By default this searches for the structural subscription of the ubuntu-server Team.
But depending on the use case one might overwrite the team name with `--lpname` (which can be any launchpad user, doesn't have to be a Team).
Additionally, especially when setting a personal name it is common that the filter should be switched to check for bug subscription instead of a structural subscription which can be done via `--bugsubscriber`.
```
show all bugs user paelzer is subscribed to (without date modification filter)
./ustriage.py --lpname paelzer --bugsubscriber

show all bugs user paelzer is subscribed to that were modified last month
./ustriage.py --lpname paelzer --bugsubscriber 2016-08-20 2016-09-20
```

## Bug expiration
To have some kind of tracking of the bugs subscribed by ubuntu-server as well as those tagged server-next
we have to make sure that we identify those that are dormant for too long.
Therefore by default bug expiration info is now added to the output by default.

Since these lists can be rather huge they are not opened in a browser by default.
But if wanted a user can set the option --open-expire
```
./ustriage.py 2016-09-10 2016-09-12 --open-expire
```
If instead a user is not interested at all in the expiration he can disable the report by --no-expiration
```
./ustriage.py 2016-09-10 2016-09-12 --no-expiration
```
### Further options and use cases of bug expiration
The expiration is defined as 60 days of inactivity in server-next tagged bugs, and 180 days for the other ubuntu-server subscribed bugs.
These durations as well as the tag it considers for the "active" list can be tuned via the arguments, --expire-next, --expire and --tag-next.
This can be combined with a custom bug subscriber to be useful outside of the server team triage.
So the following example for example will list any bugs subscribed by hardcoredev which are inactive for 5 or more days with the tag super-urgent.
```
./ustriage.py 2016-09-10 2016-09-12 --expire-next 5 --tag-next super-urgent --bugsubscriber hardcoredev
```
