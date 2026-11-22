"""REWE: eigener Host, Arbeitgeberprüfung und mehrseitiger Kataloglauf."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from employer_adapters import adapter_jobs
from sources import registry
from test_penny import listing, posting


def test_rewe_search_pagination_company_and_radius():
    source = registry()['rewe']
    fetched = []

    def get(url, configured):
        assert configured == source
        assert urlsplit(url).hostname == 'karriere.rewe.de'
        fetched.append(url)
        if '/suche?' in url:
            params = parse_qs(urlsplit(url).query)
            assert params['range'] == ['50']
            assert params['location'] == ['Waiblingen']
            assert 48 < float(params['lat'][0]) < 49
            assert 9 < float(params['lng'][0]) < 10
            index = int(params['index'][0])
            return url, listing(index, more=index < 3, brand='rewe')
        if '/1-de_DE/' in url:
            return url, posting('Waiblingen', '71332', 'REWE Markt GmbH')
        if '/2-de_DE/' in url:
            return url, posting('Hamburg', '20095', 'REWE Markt GmbH')
        return url, posting('Waiblingen', '71332', 'PENNY Markt GmbH')

    report = {'status': 'done', 'filtered': 0}
    jobs = list(adapter_jobs(source, SimpleNamespace(q='', max_pages=10), get, report))
    assert len(jobs) == 1
    assert jobs[0]['company'] == 'REWE Markt GmbH'
    assert len(fetched) == 6
    assert report['filtered'] == 2
    assert report['status'] == 'done'
