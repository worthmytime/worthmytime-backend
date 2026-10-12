"""Wywiad o sytuacji życiowej użytkownika: zamiana odpowiedzi na zdania, które Jev dostaje jako kontekst.

Czysta logika bez I/O. Odpowiedzi są opcjonalne; brak odpowiedzi nie tworzy żadnego zdania.
"""

from __future__ import annotations


def years(n: int) -> str:
    """Wiek słownie: 0 -> "mniej niż rok", 1 -> "1 rok", 3 -> "3 lata", 8 -> "8 lat"."""
    if n == 0:
        return "mniej niż rok"
    if n == 1:
        return "1 rok"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} lata"
    return f"{n} lat"


HOUSING = {
    "WITH_PARENTS": "Mieszka z rodzicami: nie płaci czynszu najmu ani raty za mieszkanie.",
    "RENT": "Wynajmuje mieszkanie: płaci czynsz najmu i opłaty.",
    "OWN_MORTGAGE": "Ma własne mieszkanie na kredyt: płaci ratę kredytu hipotecznego i opłaty.",
    "OWN": "Ma własne mieszkanie bez kredytu: płaci tylko opłaty i media.",
    "OTHER": "Ma inną sytuację mieszkaniową niż wynajem lub własne mieszkanie.",
}
CAR = {
    "NONE": "Nie ma samochodu.",
    "OWN": "Ma własny samochód",
    "FINANCED": "Ma samochód w leasingu albo na kredyt",
}
COMMUTE = {
    "CAR": "Do pracy dojeżdża samochodem.",
    "PUBLIC": "Do pracy dojeżdża komunikacją publiczną.",
    "BIKE_WALK": "Do pracy chodzi pieszo albo jeździ rowerem.",
    "NONE": "Nie dojeżdża do pracy.",
}
WORK_MODE = {
    "REMOTE": "Pracuje zdalnie, z domu.",
    "HYBRID": "Pracuje hybrydowo: częściowo z domu, częściowo na miejscu.",
    "ONSITE": "Pracuje na miejscu, poza domem.",
    "NOT_WORKING": "Obecnie nie pracuje.",
}
EMPLOYMENT = {
    "EMPLOYEE": "Jest zatrudniony na etacie lub umowie.",
    "SELF_EMPLOYED": "Prowadzi własną działalność.",
    "STUDENT": "Studiuje lub się uczy.",
    "RETIRED": "Jest na emeryturze lub rencie.",
    "OTHER": "Ma inne źródło utrzymania niż etat i własna działalność.",
}


# pytania tak/nie z grupy "zdrowie i rozwój": klucz, zdanie dla "tak", zdanie dla "nie"
YES_NO = [
    ("regular_health_costs", "Ma stałe wydatki na leczenie lub leki.", "Nie ma stałych wydatków na leczenie."),
    ("does_sport", "Regularnie uprawia sport lub chodzi na siłownię.", "Nie uprawia regularnie sportu."),
    ("pays_for_education", "Płaci za naukę, studia lub kursy.", "Nie płaci za naukę ani kursy."),
]


def summary(context: dict | None) -> list[str]:
    """Zdania opisujące użytkownika, w stałej kolejności grup.

    Grupy: mieszkanie, transport, praca, sprzęt, oszczędności, zwierzęta, zdrowie i rozwój, własne kategorie, dopisek.
    """
    c = context or {}
    out: list[str] = []

    if c.get("housing") in HOUSING:
        out.append(HOUSING[c["housing"]])
    if c.get("household_size") is not None:
        size = c["household_size"]
        out.append("Mieszka sam." if size == 1 else f"Gospodarstwo domowe liczy {size} os.")
    if c.get("children") is not None:
        kids = c["children"]
        out.append("Nie ma dzieci na utrzymaniu." if kids == 0 else f"Ma na utrzymaniu dzieci: {kids}.")

    if c.get("car") in CAR:
        car = CAR[c["car"]]
        if c["car"] != "NONE":
            age = c.get("car_age_years")
            car += f" (wiek auta: {years(age)})." if age is not None else "."
        out.append(car)
    if c.get("commute") in COMMUTE:
        out.append(COMMUTE[c["commute"]])

    if c.get("work_mode") in WORK_MODE:
        out.append(WORK_MODE[c["work_mode"]])
    if c.get("employment") in EMPLOYMENT:
        out.append(EMPLOYMENT[c["employment"]])

    if c.get("phone_age_years") is not None:
        out.append(f"Jego telefon ma {years(c['phone_age_years'])}.")
    if c.get("computer_age_years") is not None:
        out.append(f"Jego komputer ma {years(c['computer_age_years'])}.")

    months = c.get("emergency_fund_months")
    if c.get("has_emergency_fund") is False:
        out.append("Nie ma jeszcze poduszki finansowej.")
    elif months:
        out.append(f"Ma poduszkę finansową na {months} mies. wydatków.")
    elif c.get("has_emergency_fund"):
        out.append("Ma poduszkę finansową.")
    if c.get("saves_regularly") is not None:
        out.append("Regularnie odkłada pieniądze." if c["saves_regularly"] else "Nie odkłada pieniędzy regularnie.")
    if c.get("invests") is not None:
        out.append("Inwestuje część oszczędności." if c["invests"] else "Nie inwestuje.")

    pets = (c.get("pets_description") or "").strip()
    if c.get("has_pets") is False:
        out.append("Nie ma zwierząt domowych.")
    elif pets:
        out.append(f"Ma zwierzęta domowe: {pets}.")
    elif c.get("has_pets"):
        out.append("Ma zwierzęta domowe.")

    for key, yes, no in YES_NO:
        if c.get(key) is not None:
            out.append(yes if c[key] else no)

    # własne kategorie użytkownika: jego nazwa i opis, bez interpretacji
    for item in c.get("custom") or []:
        name, description = (item.get("name") or "").strip(), (item.get("description") or "").strip()
        if name and description:
            out.append(f"{name}: {description}")
    notes = (c.get("notes") or "").strip()
    if notes:
        out.append(f"Sam o sobie dodaje: {notes}")
    return out
