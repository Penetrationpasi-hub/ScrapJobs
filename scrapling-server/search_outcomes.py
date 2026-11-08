"""Explicit source-owned empty searches, never inferred from an empty shell."""
import re

from scrapling import Selector

from extraction import plain


def festo_no_matches(html, source, query):
    """Festo's empty search embeds ten unrelated newest-job recommendations."""
    if source.key != "festo" or not query.strip():
        return False
    page = Selector(html)
    alerts = page.css("div#noresults")
    if len(alerts) != 1:
        return False
    alert = alerts[0]
    if "hidden" in alert.attrib or re.search(r"display\s*:\s*none", alert.attrib.get("style", ""), re.I):
        return False
    terms = alert.css("#attention .securitySearchString")
    inputs = page.css('form[name="keywordsearch"] input[name="q"]::attr(value)').getall()
    if len(terms) != 1 or len(inputs) != 1:
        return False

    def normalized(value):
        return " ".join(value.split()).casefold()

    expected = normalized(query)
    if normalized(plain(terms[0].get())) != expected or normalized(inputs[0]) != expected:
        return False
    message = normalized(plain(alert.css("#attention").get() or ""))
    recommendations = normalized(plain(alert.css("#noresults-message").get() or ""))
    return (message.startswith("there are currently no open positions matching")
            and "most recent jobs posted by festo" in recommendations
            and "listed below for your convenience" in recommendations)
