"""
ONPE API field-name candidate lists for parser.py.

The actual ONPE API field names are unknown until the discovery phase runs.
Each tuple contains candidate key names in priority order — the first match wins.
Add confirmed names at the front once discovery has been run.

TODO: replace speculative candidates with confirmed key names after discovery.
"""

# National summary
ACTAS_PCT_KEYS = ("porcentajeActas", "pctActas", "actas_pct", "porcentaje", "pct")

CANDIDATO_1_NOMBRE_KEYS = (
    "candidato1Nombre", "nombreCandidato1", "candidato_1_nombre", "nombre1",
)
CANDIDATO_1_VOTOS_KEYS = (
    "candidato1Votos", "votosCandidato1", "candidato_1_votos", "votos1",
)
CANDIDATO_1_PCT_KEYS = (
    "candidato1Pct", "porcentajeCandidato1", "candidato_1_pct", "pct1",
    "porcentajeVotosCandidato1",
)

CANDIDATO_2_NOMBRE_KEYS = (
    "candidato2Nombre", "nombreCandidato2", "candidato_2_nombre", "nombre2",
)
CANDIDATO_2_VOTOS_KEYS = (
    "candidato2Votos", "votosCandidato2", "candidato_2_votos", "votos2",
)
CANDIDATO_2_PCT_KEYS = (
    "candidato2Pct", "porcentajeCandidato2", "candidato_2_pct", "pct2",
    "porcentajeVotosCandidato2",
)

BLANCOS_KEYS = ("votosBlancos", "blancos", "votos_blancos", "nroBlancos")
NULOS_KEYS = ("votosNulos", "nulos", "votos_nulos", "nroNulos")
TOTAL_KEYS = ("totalActas", "actas_total", "total", "nroActas", "actas")

# Regional breakdown list
REGIONS_LIST_KEYS = (
    "departamentos", "regiones", "regions", "breakdown",
    "resultadosDepartamento", "resultadosRegion",
)

# Region sub-fields
REGION_CODIGO_KEYS = ("codigoDepartamento", "codDepartamento", "region_codigo", "codigo")
REGION_NOMBRE_KEYS = ("nombreDepartamento", "nomDepartamento", "region_nombre", "nombre")
