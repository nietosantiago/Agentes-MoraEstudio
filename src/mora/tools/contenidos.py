"""Tools del agente de contenidos: calendario editorial y borradores para redes."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .comercial import SinArgs  # noqa: F401  (re-export)


class CalendarioArgs(BaseModel):
    mes: str = Field(pattern=r"^\d{4}-\d{2}$")


def calendario_contenidos(ctx, a: CalendarioArgs) -> dict:
    posts = ctx.db.query("SELECT * FROM posts WHERE fecha LIKE ? ORDER BY fecha", (f"{a.mes}-%",))
    return {"mes": a.mes, "posts": posts}


def pilares_contenido(ctx, a) -> dict:
    texto = ctx.marca.reference("pilares_contenido.md")
    pilares = [line.split("|")[1].strip() for line in texto.splitlines()
               if line.startswith("|") and not line.startswith("| Pilar") and not line.startswith("|---")]
    return {"pilares": pilares, "detalle": texto, "dias_publicacion": [1, 4]}  # martes y viernes


def obras_publicables(ctx, a) -> dict:
    return {"obras": ctx.db.query("SELECT id, nombre, etapa, notas FROM obras WHERE publicable=1 ORDER BY id")}


class PostArgs(BaseModel):
    fecha: date
    red: Literal["instagram", "facebook", "tiktok"] = "instagram"
    formato: Literal["carrusel", "reel", "foto", "historia"]
    pilar: str
    texto: str = Field(min_length=20, max_length=2200)
    hashtags: str = ""
    brief_visual: str = Field(min_length=10, description="Brief en texto para la diseñadora gráfica (no imágenes)")
    obra_id: str | None = None


class ProgramarPostsArgs(BaseModel):
    posts: list[PostArgs] = Field(min_length=1, max_length=20)


def programar_posts(ctx, a: ProgramarPostsArgs) -> dict:
    ids = []
    for p in a.posts:
        pid = f"POST-{p.fecha.isoformat()}"
        ctx.db.insert("posts", {**p.model_dump(mode="json"), "id": pid, "estado": "programado"},
                      on_conflict_nothing=True)
        ids.append(pid)
    return {"programados": ids, "nota": "publicación simulada: quedan en estado 'programado'"}
