"""Synthetic articles: the offline demo and the test fixtures.

* DEMO_PAGE (900001918) — "Suomen sisällissota (demo)": ~70 revisions 2004–2025 written to mimic
  the real article's story: it starts as *vapaussota*, the name is fought over, *punakapina* is
  inserted and removed, a neutral naming paragraph arrives, the death toll is edited back and
  forth. Lets frontend and API work before the real dataset is loaded. Clearly not real data.
* ABC_PAGE (900000001) — the §8 synthetic test: A B C (2010) → A X C (2012) → A B C (2014).

    python -m ingest.synthetic > data/demo.jsonl     # dump as JSONL (same format as iter_jsonl)
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta

from ingest.load_articles import Page, Revision

DEMO_PAGE = 900001918
ABC_PAGE = 900000001

INTRO_V = "'''Suomen vapaussota''' oli vuonna 1918 käyty sota, jossa [[Suojeluskunta|valkoinen armeija]] vapautti maan venäläisistä ja punaisista."
INTRO_S = "'''Suomen sisällissota''' käytiin [[Suomen senaatti|senaatin]] ja [[Kansanvaltuuskunta|kansanvaltuuskunnan]] joukkojen välillä 27. tammikuuta – 15. toukokuuta 1918."
INTRO_K = "'''Suomen sisällissota''' eli kansalaissota käytiin senaatin ja kansanvaltuuskunnan joukkojen välillä 27. tammikuuta – 15. toukokuuta 1918."
WHITES = "Valkoisten joukkoja johti kenraali [[C. G. E. Mannerheim]]."
REDS = "Punaisten joukot koostuivat pääosin [[Punakaarti|punakaarteista]]."
REDS_LOADED = "Punaiset olivat Venäjän yllyttämiä kapinallisia, jotka pyrkivät kaappaamaan vallan."
PUNAKAPINA = "Sota oli punakapina, jonka lailliset viranomaiset kukistivat."
GERMANY = "Saksan keisarikunnan joukot nousivat maihin Hankoon huhtikuussa 1918."
TAMPERE = "Ratkaiseva taistelu käytiin [[Tampereen taistelu|Tampereella]] maalis–huhtikuussa 1918."
DEATHS_37 = "Sodassa kuoli noin 37 000 ihmistä.<ref>Sotasurmaprojekti</ref>"
DEATHS_38 = "Sodassa kuoli noin 38 000 ihmistä.<ref>{{Verkkoviite|nimeke=Sotasurmat}}</ref>"
TERROR_W = "Valkoinen terrori ja vankileirit vaativat enemmän uhreja kuin itse taistelut."
TERROR_R = "Punainen terrori kohdistui erityisesti maanomistajiin ja virkamiehiin."
NAMES = ("Sodalle on annettu erilaisia nimiä, kuten vapaussota, punakapina, luokkasota ja "
         "kansalaissota, jotka heijastelevat eri osapuolten näkemyksiä.")
NAMES_2 = "Nykyään tutkimuksessa käytetään yleisimmin neutraalia nimeä sisällissota."
CAMPS = "Sodan jälkeen noin 80 000 punaista vangittiin vankileireille."
CAMPS_LOADED = "Sodan jälkeen kapinalliset koottiin leireille, joissa moni kuoli omaan heikkouteensa."
LEGACY = "Sota jätti syvät jäljet suomalaiseen yhteiskuntaan vuosikymmeniksi."
RECONC = "Vuoden 2018 muistovuonna sotaa käsiteltiin laajasti sovinnon hengessä."
VANDAL = "TÄMÄ ON VALETTA LOL!!!"


def _wikitext(sentences: list[str]) -> str:
    """Join into paragraphs of three sentences, with an infobox and a category to strip."""
    paras = [" ".join(sentences[i:i + 3]) for i in range(0, len(sentences), 3)]
    return ("{{Sotatiedot|nimi=Suomen sota 1918|aika=1918|koordinaatit={{coord|61|29|52|N|23|45|39|E|type:event}}}}\n" + "\n\n".join(paras)
            + "\n\n== Katso myös ==\n* [[Talvisota]]\n\n[[Luokka:Suomen sisällissota]]")


def _demo_script():
    """(date, user, anonymous, comment, new sentence list) — each a full revision."""
    users = ["Kalervo", "Aino_K", "Punatähti", "Valkokaarti", "Historioitsija", "Tutkija88",
             "Siivooja", "Neutraali"]
    s = [INTRO_V, WHITES, REDS_LOADED, TAMPERE, GERMANY, DEATHS_37]
    d = datetime(2004, 3, 14, 12, 0, 0)
    yield d, users[0], False, "Uusi artikkeli", list(s)

    def step(days, user, comment, new, anon=False, keep=True):
        """keep=False: a revision that is undone next (vandalism), the state stays as it was."""
        nonlocal d, s
        d = d + timedelta(days=days, minutes=37)
        if keep:
            s = list(new)
        return d, user, anon, comment, list(new)

    yield step(40, users[1], "lisätty kansalaissodan terrori", s + [TERROR_R])
    yield step(90, users[2], "punakapina pois, ei neutraali", [x for x in s if x != REDS_LOADED] + [REDS])
    yield step(2, users[3], "kumottu", [REDS_LOADED if x == REDS else x for x in s])
    yield step(1, users[2], "kumottu, POV", [REDS if x == REDS_LOADED else x for x in s])
    yield step(1, users[3], "palautettu", [REDS_LOADED if x == REDS else x for x in s])
    yield step(30, "84.250.1.10", "", s + [PUNAKAPINA], anon=True)
    yield step(0.2, users[6], "poistettu POV", [x for x in s if x != PUNAKAPINA])
    # Name war: vapaussota vs sisällissota (2005–2007)
    for k in range(5):
        yield step(70, users[2], "nimi: sisällissota on vakiintunut", [INTRO_S if x == INTRO_V else x for x in s])
        yield step(9, users[3], "nimi: vapaussota", [INTRO_V if x == INTRO_S else x for x in s])
    yield step(12, users[4], "artikkelin nimi muutettu", [INTRO_S if x == INTRO_V else x for x in s])
    # Blanking vandalism (filtered by the loader)
    yield step(20, "91.152.3.4", "", [VANDAL], anon=True, keep=False)
    yield step(0.01, users[6], "kumottu muokkaus", list(s))
    # Death toll war
    for k in range(4):
        yield step(60, users[5], "luvut Sotasurmaprojektin mukaan", [DEATHS_38 if x == DEATHS_37 else x for x in s])
        yield step(5, users[0], "vanha luku", [DEATHS_37 if x == DEATHS_38 else x for x in s])
    yield step(10, users[5], "luvut lähteen mukaan", [DEATHS_38 if x == DEATHS_37 else x for x in s])
    yield step(45, users[4], "terrori molemmin puolin", s + [TERROR_W, CAMPS_LOADED])
    yield step(4, users[2], "neutraalimpi", [CAMPS if x == CAMPS_LOADED else x for x in s])
    yield step(3, users[3], "kumottu", [CAMPS_LOADED if x == CAMPS else x for x in s])
    yield step(2, users[4], "lähteen mukaan", [CAMPS if x == CAMPS_LOADED else x for x in s])
    yield step(200, users[7], "nimitykset-osio", s[:1] + [NAMES] + s[1:])
    yield step(150, users[7], "neutraali kieli", [REDS if x == REDS_LOADED else x for x in s])
    yield step(9, "88.112.40.2", "", [REDS_LOADED if x == REDS else x for x in s], anon=True)
    yield step(0.1, users[6], "kumottu", [REDS if x == REDS_LOADED else x for x in s])
    for k in range(6):            # quiet years, small additions
        extra = [LEGACY] if k == 2 else []
        yield step(300, users[k % 8], "kielenhuoltoa", s + [x for x in extra if x not in s])
    yield step(100, users[7], "tutkimuksen nimi", [x for x in s] + [NAMES_2])
    yield step(400, users[1], "kansalaissota", [INTRO_K if x == INTRO_S else x for x in s])
    yield step(2, users[4], "sisällissota", [INTRO_S if x == INTRO_K else x for x in s])
    yield step(60, users[1], "muistovuosi", s + [RECONC])
    for k in range(5):
        yield step(250, users[(k + 3) % 8], "pieniä korjauksia", list(s))


def _rev(i: int, when: datetime, user: str, anon: bool, comment: str, text: str) -> Revision:
    return Revision(rev_id=i, ts=when, user=user, anonymous=anon, comment=comment, minor=False,
                    sha1=hashlib.sha1(text.encode()).hexdigest(), text=text)


def demo_page() -> Page:
    page = Page(DEMO_PAGE, "Suomen sisällissota (demo)")
    for i, (when, user, anon, comment, sents) in enumerate(_demo_script(), start=1):
        page.revisions.append(_rev(DEMO_PAGE * 1000 + i, when, user, anon, comment, _wikitext(sents)))
    return page


def abc_page() -> Page:
    page = Page(ABC_PAGE, "ABC test")
    a, b, c, x = ("Lause A on ensimmäinen.", "Lause B on kiistelty.", "Lause C on viimeinen.",
                  "Lause B on kiistanalainen.")
    for i, (year, sents, user) in enumerate([(2010, [a, b, c], "u1"), (2012, [a, x, c], "u2"),
                                              (2014, [a, b, c], "u3")], start=1):
        page.revisions.append(_rev(i, datetime(year, 1, 1), user, False, f"rev{i}", " ".join(sents)))
    return page


def demo_pages() -> list[Page]:
    return [demo_page(), abc_page()]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in demo_pages():
        for r in p.revisions:
            print(json.dumps(dict(page_id=p.page_id, title=p.title, rev_id=r.rev_id,
                                  timestamp=r.ts.isoformat() + "Z", user=r.user, anonymous=r.anonymous,
                                  comment=r.comment, minor=r.minor, sha1=r.sha1, text=r.text),
                             ensure_ascii=False))
