"""Regression: Koordinatenfilter, Pagination und verifizierter Anzeigenort."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from penny_adapter import penny
from safe_http import FetchError
from sources import registry


def listing(ident, more=False, brand='penny'):
    return ('<div data-job-search-results="root"><div class="job-search__item">'
            f'<a class="job-search__item-content" href="/jobs/{brand}/{ident}-de_DE/Job.html?feedId=172701&amp;utm_source=careersite">Job</a>'
            '<div class="job-search__item-multilocation">71332 Waiblingen</div></div></div>'
            + ('<a class="job-search-button-next" href="?index=2">Weiter</a>' if more else ''))


def posting(city, postcode, company='PENNY Markt GmbH'):
    return '<script type="application/ld+json">' + json.dumps({
        '@type': 'JobPosting', 'title': 'Verkäufer / Kassierer (m/w/d)',
        'hiringOrganization': {'name': company},
        'jobLocation': {'address': {'addressLocality': city, 'postalCode': postcode,
                                    'addressCountry': 'DE'}},
    }) + '</script>'


def test_pagination_and_detail_location():
    requests = []

    def get(url, source):
        requests.append(url)
        if '/suchen?' in url:
            params = parse_qs(urlsplit(url).query)
            assert params['range'] == ['50']
            assert params['location'] == ['Waiblingen']
            assert 48 < float(params['lat'][0]) < 49
            assert 9 < float(params['lng'][0]) < 10
            index = int(params['index'][0])
            return url, listing(index, more=index == 1)
        # Teaser behauptet Waiblingen; der verifizierte Ort hat Vorrang.
        return url, posting('Waiblingen', '71332') if '/1-de_DE/' in url else posting('Hamburg', '20095')

    report = {'filtered': 0, 'status': 'done'}
    jobs = list(penny(registry()['penny'], SimpleNamespace(q='', max_pages=10), get, report))
    assert len(jobs) == 1
    assert report['filtered'] == 1
    assert len(requests) == 4
    assert report['status'] == 'done'


def test_missing_list_is_not_successful_empty_search():
    with pytest.raises(FetchError):
        list(penny(registry()['penny'], SimpleNamespace(q=''),
                   lambda url, source: (url, '<html>Wartung</html>'), {'filtered': 0}))


def test_page_limit_is_partial():
    report = {'filtered': 0, 'status': 'done'}

    def get(url, source):
        return url, listing(1, True) if '/suchen?' in url else posting('Waiblingen', '71332')

    list(penny(registry()['penny'], SimpleNamespace(q='', max_pages=1), get, report))
    assert report['status'] == 'result_limit'
