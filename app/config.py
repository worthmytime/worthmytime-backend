import re

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-secret-change-me-dev-secret-change-me"
MIN_JWT_SECRET_LENGTH = 32

_FLAG_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
_FLAG_VALUES = {"true": True, "1": True, "on": True, "false": False, "0": False, "off": False}


def parse_feature_flags(raw: str) -> tuple[dict[str, bool], list[str]]:
    """`reports,tags=false` -> ({"reports": True, "tags": False}, []); drugi element to wpisy nie do odczytania."""
    flags: dict[str, bool] = {}
    invalid: list[str] = []
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        name, sep, value = (p.strip().lower() for p in entry.partition("="))
        enabled = _FLAG_VALUES.get(value) if sep else True  # sama nazwa oznacza flagę włączoną
        if enabled is None or not _FLAG_NAME.fullmatch(name):
            invalid.append(entry)
            continue
        flags[name] = enabled
    return flags, invalid


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./worthmytime.db"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_ttl_hours: int = 24 * 7
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    rate_limit_api_per_minute: int = 300
    rate_limit_auth_per_minute: int = 20
    rate_limit_ai_per_minute: int = 20  # prośby o podpowiedź Jev z jednego adresu IP
    login_max_failures: int = 5
    login_lock_seconds: int = 900
    # sesja w cookie: SameSite=lax przy froncie i API na tej samej stronie (site); przy różnych domenach "none"
    # (wymaga Secure i konkretnej domeny w CORS_ORIGINS)
    cookie_samesite: str = "lax"
    cookie_secure: bool | None = None  # brak = włączone poza trybem DEBUG
    cookie_domain: str | None = None
    trust_proxy: bool = False  # True tylko za zaufanym reverse proxy (adres z X-Forwarded-For)
    # Jev (TypeSafe AI): klucz tylko w backendzie; adres może wskazywać proxy LiteLLM (http://litellm:4000/typesafe)
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_model: str = "jev-latest"
    typesafe_timeout_seconds: float = 15.0
    # Asystent AI: model OpenAI przez oficjalną bibliotekę `openai`. Klucz i nazwa modelu tylko w backendzie;
    # bez nich asystent jest wyłączony. Klucz można podać jako ASSISTANT_API_KEY albo standardowe OPENAI_API_KEY.
    assistant_api_key: str = Field(default="", validation_alias=AliasChoices("assistant_api_key", "openai_api_key"))
    assistant_model: str = ""
    assistant_timeout_seconds: float = 60.0
    # przełączniki funkcji: lista po przecinku, np. "reports,tags=false" (sama nazwa = włączona)
    feature_flags: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else not self.debug

    @property
    def feature_flag_map(self) -> dict[str, bool]:
        return parse_feature_flags(self.feature_flags)[0]

    def production_problems(self) -> list[str]:
        """Błędy konfiguracji niedopuszczalne poza trybem DEBUG."""
        problems = []
        if self.jwt_secret == DEFAULT_JWT_SECRET:
            problems.append("JWT_SECRET ma wartość domyślną - ustaw własny sekret")
        elif len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET jest krótszy niż {MIN_JWT_SECRET_LENGTH} znaków")
        if self.cookie_samesite.lower() not in ("lax", "strict", "none"):
            problems.append("COOKIE_SAMESITE musi mieć wartość lax, strict albo none")
        elif self.cookie_samesite.lower() == "none" and not self.effective_cookie_secure:
            problems.append("COOKIE_SAMESITE=none wymaga COOKIE_SECURE=true")
        if not self.typesafe_base_url.lower().startswith(("https://", "http://")):
            problems.append("TYPESAFE_BASE_URL musi zaczynać się od https:// albo http://")
        invalid = parse_feature_flags(self.feature_flags)[1]
        if invalid:
            problems.append(f"FEATURE_FLAGS zawiera niepoprawne wpisy: {', '.join(invalid)}")
        return problems


settings = Settings()
