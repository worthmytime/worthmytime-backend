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


def summary(context: dict | None) -> list[str]:
    """Zdania opisujące użytkownika, w stałej kolejności grup: mieszkanie, transport, praca, sprzęt, pozostałe."""
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

    if c.get("has_emergency_fund") is not None:
        out.append("Ma poduszkę finansową." if c["has_emergency_fund"] else "Nie ma jeszcze poduszki finansowej.")
    if c.get("has_pets") is not None:
        out.append("Ma zwierzęta domowe." if c["has_pets"] else "Nie ma zwierząt domowych.")
    notes = (c.get("notes") or "").strip()
    if notes:
        out.append(f"Sam o sobie dodaje: {notes}")
    return out
