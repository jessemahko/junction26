"""Wikitext cleaning and Finnish sentence splitting (no database needed)."""
from ingest.history import match_rewrites
from ingest.sentences import clean_wikitext, sentences, split_sentences


def test_abbreviations_dates_and_initials_do_not_split():
    p = ("Suomi julistautui itsenäiseksi 6. joulukuuta 1917. Valkoisia johti C. G. E. Mannerheim, "
         "esim. Tampereella. Sota päättyi n. 15. toukokuuta.")
    assert split_sentences(p) == [
        "Suomi julistautui itsenäiseksi 6. joulukuuta 1917.",
        "Valkoisia johti C. G. E. Mannerheim, esim. Tampereella.",
        "Sota päättyi n. 15. toukokuuta.",
    ]


def test_markup_is_stripped():
    w = ("{{Infobox|a={{nested}}}}'''Sota''' oli [[Suomi|Suomessa]] käyty sota.<ref>lähde</ref>\n"
         "[[Tiedosto:Kuva.jpg|pienois|Kuvateksti [[linkki]]]]\n== Otsikko ==\n{| class=wikitable\n|-\n| solu\n|}\n"
         "[[Luokka:Sodat]]")
    assert [s for _, s in sentences(w)] == ["Sota oli Suomessa käyty sota."]


def test_redirect_is_empty():
    assert clean_wikitext("#OHJAUS [[Suomen sisällissota]]") == ""


def test_hash_ignores_quote_style_and_spacing():
    a = sentences("Sotaa kutsuttiin ”vapaussodaksi” pitkään.")
    b = sentences('Sotaa  kutsuttiin "vapaussodaksi" pitkään .')
    assert a[0][0] == b[0][0]


def test_coordinates():
    from ingest.geo import named_places, own_coordinates
    assert own_coordinates("{{coord|62|47|57|N|030|09|20|E|region:FI-13|display=title}}") == (62.79917, 30.15556)
    assert own_coordinates("{{Koordinaatit|60.1699|24.9384|display=title}}") == (60.1699, 24.9384)
    assert own_coordinates("|lat_deg = 60 |lat_min=9 |lat_dir=N\n|lon_deg=24|lon_min=59\n") == (60.15, 24.98333)
    assert own_coordinates("| latd = 60 | latm = 42 | longd = 28 | longm = 45") == (60.7, 28.75)
    assert own_coordinates("Ei koordinaatteja.") is None
    assert named_places("| paikka = [[Tampere]], [[Suomi]]\n") == ["Tampere", "Suomi"]


def test_event_years():
    from ingest.event_time import years
    assert years("Sisällissota käytiin vuonna 1918.") == (1918, 1918)
    assert years("Itsenäisyys julistettiin 6.12.1917 ja sota alkoi 1918.") == (1917, 1918)
    assert years("Teollistuminen alkoi 1800-luvulla.") == (1800, 1899)
    assert years("1920-luvun alussa tilanne rauhoittui.") == (1920, 1929)
    assert years("Molemmilla oli noin 80 000 sotilasta ja 1 424 kuoli.") is None
    assert years("Ei vuosilukuja tässä lauseessa.") is None


def test_rewrite_matching():
    removed = [(b"1", "Sodassa kuoli noin 37 000 ihmistä."), (b"2", "Täysin eri asia tässä lauseessa.")]
    added = [(b"3", "Sodassa kuoli noin 38 000 ihmistä.")]
    assert match_rewrites(removed, added) == {b"3": b"1"}
