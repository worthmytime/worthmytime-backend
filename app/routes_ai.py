"""Podpowiedzi Jev dla frontendu: kategorie wydatków i kolumny pliku importu (klucz API zostaje w backendzie)."""

from sanic import Blueprint, Request

from . import jev, life
from .errors import ApiError
from .helpers import client_ip, current_user, ok, parse
from .schemas import CategorizeIn, MapColumnsIn

bp = Blueprint("ai", url_prefix="/api/v1")


def _check_ai_rate(request: Request) -> None:
    """Każde wywołanie Jev kosztuje, a endpointy działają też bez konta, więc mają własny, niższy limit na adres IP."""
    wait = request.app.ctx.limiter.check_ai(client_ip(request))
    if wait:
        message = "Zbyt wiele próśb o podpowiedź, spróbuj ponownie za chwilę"
        raise ApiError(message, 429, headers={"Retry-After": str(wait)})


@bp.post("/ai/categorize")
async def ai_categorize(request: Request):
    """Propozycja kategorii budżetu dla opisów wydatków (np. sprzedawców z wyciągu)."""
    data = parse(CategorizeIn, request)
    _check_ai_rate(request)
    # zalogowany użytkownik z wypełnionym wywiadem: Jev dostaje opis jego sytuacji życiowej jako kontekst
    user = await current_user(request)
    context = life.summary(user.life_context) if user is not None else []
    state, questions = jev.categorize_request([i.description for i in data.items], context)
    answers = await jev.system_one(state, questions)
    return ok({"suggestions": jev.categories_from(answers, [i.key for i in data.items])})


@bp.post("/ai/map-columns")
async def ai_map_columns(request: Request):
    """Która kolumna pliku z historią transakcji jest datą, kwotą, opisem i walutą."""
    data = parse(MapColumnsIn, request)
    _check_ai_rate(request)
    columns = [c.model_dump() for c in data.columns]
    state, questions = jev.mapping_request(columns)
    answers = await jev.system_one(state, questions)
    return ok({"mapping": jev.mapping_from(answers, columns)})
