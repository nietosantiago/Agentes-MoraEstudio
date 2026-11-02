from .administrativo import AgenteAdministrativo
from .comercial import AgenteComercial
from .contenidos import AgenteContenidos
from .proyectos import AgenteProyectos

AGENTES_CLASES = {"comercial": AgenteComercial, "contenidos": AgenteContenidos,
                  "administrativo": AgenteAdministrativo, "proyectos": AgenteProyectos}
