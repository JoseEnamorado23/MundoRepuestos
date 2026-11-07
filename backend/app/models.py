"""Importa todos los modelos para que queden registrados en Base.metadata (Alembic y pruebas)."""

from app.core.base import Base  # noqa: F401
from app.modules.auditoria import models as _auditoria  # noqa: F401
from app.modules.cajas import models as _cajas  # noqa: F401
from app.modules.catalogo import models as _catalogo  # noqa: F401
from app.modules.fiscal import models as _fiscal  # noqa: F401
from app.modules.identidad import models as _identidad  # noqa: F401
from app.modules.inventario import models as _inventario  # noqa: F401
from app.modules.organizacion import models as _organizacion  # noqa: F401
from app.modules.referencia import models as _referencia  # noqa: F401
from app.modules.sync import models as _sync  # noqa: F401
from app.modules.ventas import models as _ventas  # noqa: F401
