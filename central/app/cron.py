"""Cron de 5 campos (minuto hora dia-do-mês mês dia-da-semana), sem dependências: valida, calcula a próxima
ocorrência num fuso horário (zoneinfo) e descreve em português.

Suporta *, listas (1,3,5), faixas (1-5), passos (*/15, 8-18/2), nomes (jan-dec, sun-sat) e os atalhos
@hourly, @daily, @weekly, @monthly, @yearly. Como no cron clássico, se dia-do-mês E dia-da-semana forem
restritos, basta um dos dois bater."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
           "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DAYS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
FIELDS = (("minuto", 0, 59, {}), ("hora", 0, 23, {}), ("dia do mês", 1, 31, {}), ("mês", 1, 12, MONTHS),
          ("dia da semana", 0, 7, DAYS))
DAY_PT = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
MONTH_PT = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
            "novembro", "dezembro"]


class CronError(ValueError):
    pass


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise CronError(f"fuso horário desconhecido: '{name}' (ex.: America/Sao_Paulo, UTC)") from None


def _value(tok: str, names: dict, label: str) -> int:
    tok = tok.strip().lower()
    if tok in names:
        return names[tok]
    if not tok.isdigit():
        raise CronError(f"valor inválido no campo {label}: '{tok}'")
    return int(tok)


def _field(expr: str, label: str, lo: int, hi: int, names: dict) -> set[int]:
    out = set()
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) < 1:
                raise CronError(f"passo inválido no campo {label}: '/{s}'")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = _value(x, names, label), _value(y, names, label)
        else:
            a = _value(part, names, label)
            b = hi if step > 1 else a
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise CronError(f"fora do intervalo no campo {label} ({lo}-{hi}): '{part}'")
        out.update(range(a, b + 1, step))
    return out


class Cron:
    def __init__(self, expr: str):
        self.expr = ALIASES.get((expr or "").strip().lower(), (expr or "").strip())
        parts = self.expr.split()
        if len(parts) != 5:
            raise CronError("o cron precisa de 5 campos: minuto hora dia-do-mês mês dia-da-semana (ex.: '0 9 * * 1-5')")
        self.raw = parts
        sets = [_field(p, *spec) for p, spec in zip(parts, FIELDS, strict=True)]
        self.minutes, self.hours, self.days, self.months, dows = sets
        self.dows = {d % 7 for d in dows}  # 7 também é domingo
        self.dom_any, self.dow_any = parts[2] == "*", parts[4] == "*"

    def _day_ok(self, d: datetime) -> bool:
        dom = d.day in self.days
        dow = (d.weekday() + 1) % 7 in self.dows  # Python: segunda=0; cron: domingo=0
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow
        if self.dow_any:
            return dom
        return dom or dow

    def next_after(self, after: datetime, tz: str = "UTC") -> datetime:
        """Próxima ocorrência estritamente depois de `after` (aware), devolvida em UTC."""
        z = zone(tz)
        t = after.astimezone(z).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
        limit = t + timedelta(days=366 * 5)
        while t < limit:
            if t.month not in self.months:
                t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if not self._day_ok(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
                continue
            if t.minute not in self.minutes:
                t += timedelta(minutes=1)
                continue
            return t.replace(tzinfo=z).astimezone(UTC)
        raise CronError("o cron nunca dispara (ex.: 31 de fevereiro)")

    def min_interval_minutes(self, tz: str = "UTC") -> float:
        """Menor intervalo entre disparos consecutivos na próxima semana (para barrar 'a cada minuto')."""
        t, prev, best = datetime.now(UTC), None, float("inf")
        for _ in range(60):
            t = self.next_after(t, tz)
            if prev is not None:
                best = min(best, (t - prev).total_seconds() / 60)
            prev = t
        return best

    def describe(self) -> str:
        m, h, dom, mon, dow = self.raw
        if not (m.isdigit() and h.isdigit()):
            return f"cron {self.expr}"
        when = f"às {int(h):02d}:{int(m):02d}"
        if dom == "*" and mon == "*" and dow == "*":
            return f"todo dia {when}"
        if dom == "*" and mon == "*":
            days = sorted(self.dows)
            if days == [1, 2, 3, 4, 5]:
                return f"de segunda a sexta {when}"
            if days == [0, 6]:
                return f"sábados e domingos {when}"
            names = [DAY_PT[d] for d in days]
            return ("toda " if len(names) == 1 and days[0] not in (0, 6) else "") + \
                (" e ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]) + f" {when}"
        if dow == "*" and mon == "*" and dom.isdigit():
            return f"todo dia {int(dom)} do mês {when}"
        if dow == "*" and dom.isdigit() and mon.isdigit():
            return f"todo {int(dom)} de {MONTH_PT[int(mon)]} {when}"
        return f"cron {self.expr}"
