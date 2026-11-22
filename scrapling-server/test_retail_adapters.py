"""ALDI, dm und toom: regionale Auswahl, Originaldaten und vollständige Listen."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import geo
from employer_adapters import adapter_jobs
from safe_http import FetchError
from sources import registry
from toom_adapter import PUBLIC_LIST


def posting(company, postcode="71332", city="Waiblingen", **extra):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": "Verkäufer (m/w/d)",
        "hiringOrganization": {"name": company},
        "jobLocation": {"address": {"postalCode": postcode, "addressLocality": city,
                                     "addressCountry": "DE"}}, **extra,
    }) + '</script>'


def run(key, get, **limits):
    report = {"status": "done", "filtered": 0}
    req = SimpleNamespace(q="", max_pages=10, max_details=100, **limits)
    jobs = list(adapter_jobs(registry()[key], req, get, report))
    return jobs, report


ALDI_ENDPOINT = ('https://karriere.aldi-sued.de/?tx_uialdisuedjobs_ads%5Baction%5D=getJobmapItems'
                 '&cHash=dynamic')
ALDI_LIST = f'<custom-job-search jobmapapi="{ALDI_ENDPOINT}"></custom-job-search>'


def aldi_url(ident):
    return f'https://jobs.aldi-sued.de/Karriere/job/Waiblingen-Verkaeufer/{ident}'


def test_aldi_coordinates_and_verified_details():
    origin = geo.center("Waiblingen")
    rows = [{"url": aldi_url(1), "lat": origin[0], "lng": origin[1]},
            {"url": aldi_url(2), "lat": 53.55, "lng": 10.0},
            {"url": aldi_url(3), "lat": None, "lng": None},
            {"url": aldi_url(4), "lat": origin[0], "lng": origin[1]},
            {"url": aldi_url(5), "lat": origin[0], "lng": origin[1]}]
    fetched = []

    def get(url, source, **options):
        fetched.append(url)
        if url == source.search:
            return url, ALDI_LIST
        if url == ALDI_ENDPOINT:
            assert options == {"accept_json": True}
            return url, json.dumps({"result": rows})
        if url == aldi_url(1):
            return url, posting("ALDI SÜD")
        if url == aldi_url(3):
            return url, posting("ALDI SÜD", "20095", "Hamburg")
        if url == aldi_url(4):
            return url, posting("ALDI SÜD", validThrough="2000-01-01")
        if url == aldi_url(5):
            return url, posting("Anderer Arbeitgeber")
        pytest.fail("Außerhalb des Umkreises: " + url)

    jobs, report = run("aldi_sued", get)
    assert len(jobs) == 1
    assert aldi_url(2) not in fetched
    assert report["filtered"] == 3


@pytest.mark.parametrize("endpoint", [
    "https://example.org/?tx_uialdisuedjobs_ads[action]=getJobmapItems",
    "https://karriere.aldi-sued.de/?tx_uialdisuedjobs_ads[action]=bookmarkAjax",
])
def test_aldi_rejects_unexpected_map_endpoints(endpoint):
    def get(url, source, **options):
        assert url == source.search
        return url, f'<custom-job-search jobmapapi="{endpoint}"></custom-job-search>'

    with pytest.raises(FetchError):
        run("aldi_sued", get)


def test_dm_postcode_prefilter_unknown_location_and_deduplication():
    base = 'https://www.dm-jobs.de/job/'
    near = base + 'verkaeufer-in-71332-waiblingen/1/'
    far = base + 'verkaeufer-in-20095-hamburg/2/'
    unknown = base + 'verkaeufer/3/'
    fetched = []

    def get(url, source, **options):
        fetched.append(url)
        if url == source.api:
            assert options['accept_xml']
            return url, '<urlset>' + ''.join(f'<url><loc>{u}</loc></url>' for u in
                                             [near, far, near, unknown, near + 'apply/']) + '</urlset>'
        if url == near.rstrip('/'):
            return url, posting('dm Deutschland')
        if url == unknown.rstrip('/'):
            return url, posting('dm Deutschland', '20095', 'Hamburg')
        pytest.fail('Unerwarteter Abruf: ' + url)

    jobs, report = run('dm', get)
    assert len(jobs) == 1
    assert report['filtered'] == 1
    assert len(fetched) == 3


def toom_url(ident):
    return f'https://toom-baumarkt.dvinci-easy.com/de/jobs/{ident}/verkaeufer'


def toom_get(fetched, *, repeat=False, missing=False):
    def get(url, source, **options):
        fetched.append(url)
        if url == PUBLIC_LIST:
            return url, ''.join(f'<a href="{toom_url(i)}">Verkäufer</a>' for i in [1, 2])
        if url.startswith(source.api):
            page = int(parse_qs(urlsplit(url).query)['page'][0])
            search = options['json_body']['search']
            assert search['location']['range'] == 50
            assert (search['location']['lat'], search['location']['lng']) == geo.center('Waiblingen')
            ident = 99 if missing else 1 if repeat else page
            # CMS-Importzeitpunkte sind keine Ablaufdaten der Originalanzeige.
            return url, json.dumps({'results': [{'externalId': str(ident), 'activeTo': '2000-01-01'}],
                                    'meta': {'page': page, 'totalPages': 2}})
        if url == toom_url(1):
            return url, posting('toom Baumarkt GmbH')
        if url == toom_url(2):
            return url, posting('toom Baumarkt GmbH', validThrough='2000-01-01')
        pytest.fail('Unerwarteter Abruf: ' + url)
    return get


def test_toom_reads_all_pages_and_original_expiry():
    fetched = []
    jobs, report = run('toom', toom_get(fetched))
    assert len(jobs) == 1
    assert jobs[0]['url'] == toom_url(1)
    assert report['filtered'] == 1
    assert report['status'] == 'done'
    assert len(fetched) == 5


@pytest.mark.parametrize('mode', ['repeat', 'missing'])
def test_toom_incomplete_list_is_not_reported_as_success(mode):
    with pytest.raises(FetchError):
        run('toom', toom_get([], **{mode: True}))


def test_dm_detail_budget_is_partial():
    source = registry()['dm']
    req = SimpleNamespace(q='', max_details=1)
    urls = [f'https://www.dm-jobs.de/job/verkaeufer-in-71332-waiblingen/{i}/' for i in [1, 2]]

    def get(url, source, **options):
        return url, ('<urlset>' + ''.join(f'<url><loc>{u}</loc></url>' for u in urls) + '</urlset>'
                     if url == source.api else posting('dm Deutschland'))

    report = {'status': 'done', 'filtered': 0}
    assert len(list(adapter_jobs(source, req, get, report))) == 1
    assert report['status'] == 'result_limit'
