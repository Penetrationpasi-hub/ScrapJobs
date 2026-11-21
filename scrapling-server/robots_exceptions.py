"""User-approved exceptions for direct robots.txt 404 responses only."""
import re
from urllib.parse import urlsplit

from carsonal_adapter import missing_robots_scope as burger_scope
from murr_adapter import missing_robots_scope as murr_scope
from persy_adapter import missing_robots_scope as persy_scope


def rems_scope(raw, source, options):
    """REMS publishes no robots.txt (404); only its public job list page is read, without any extra options."""
    if source.key != "rems" or source.adapter != "rems_list" or options:
        return False
    u = urlsplit(raw)
    return (u.scheme == "https" and u.netloc == "recruitment.rems.de" and u.path == "/stellenangebote"
            and not u.query and not u.fragment)


def missing_robots_scope(raw, source, options):
    if burger_scope(raw, source, options) or murr_scope(raw, source, options) or rems_scope(raw, source, options) \
            or persy_scope(raw, source, options):
        return True
    if source.key != "harro_hoefliger" or source.adapter != "harro_next" or options:
        return False
    u = urlsplit(raw)
    return (u.scheme == "https" and u.netloc == "hoefliger.com"
            and not u.query and not u.fragment
            and (u.path == "/karriere/stellenangebote"
                 or bool(re.fullmatch(r"/karriere/stellenangebote/[a-z0-9-]+", u.path))))


def missing_robots_statuses(source):
    """Direct robots.txt answers that count as "no robots file" for this source."""
    # Murrelektronik's www host redirects /robots.txt (301) to an HTML page.
    return {404, 301} if source.key == "murrelektronik" else {404}
