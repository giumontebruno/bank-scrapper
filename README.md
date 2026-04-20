# promo-query-py

Motor consultable de promociones bancarias y precios de combustibles para Paraguay.

## Que hace hoy

- Consulta por intencion de compra sin LLM.
- Recolecta precios base de nafta 95 y 97 desde `combustibles.com.py`.
- Recolecta promociones de `Ueno`, `Itau`, `Sudameris`, `Continental` y `BNF` desde HTML y PDFs oficiales configurados.
- Normaliza merchants y brands para cruzar promociones con combustible y rubros.
- Persiste en SQLite y soporta reruns idempotentes por `bank + month_ref`.
- Cubre categorias utiles como supermercados, combustible, gastronomia, retail, indumentaria, tecnologia, hogar, salud, viajes, entretenimiento y ferreteria cuando las fuentes publicadas lo permiten.

## Instalar

```bash
pip install -e .[dev]
```

## Configuracion por entorno

Copiar `.env.example` a `.env` y ajustar lo necesario.

Variables principales:

- `APP_ENV`: `local`, `development`, `production` u `online`
- `DATABASE_URL`: por defecto local usa SQLite; para online apuntar a PostgreSQL
- `API_HOST`: host de bind local
- `API_PORT`: puerto local
- `LOG_LEVEL`: `INFO`, `DEBUG`, etc.
- `API_CORS_ORIGINS`: lista separada por coma o `*`
- `ENABLE_ADMIN_ENDPOINTS`: `true/false`

Ejemplo local:

```bash
APP_ENV=local
DATABASE_URL=sqlite:///data/processed/catalog.sqlite
API_HOST=127.0.0.1
API_PORT=8000
LOG_LEVEL=INFO
API_CORS_ORIGINS=*
ENABLE_ADMIN_ENDPOINTS=true
```

Ejemplo online con PostgreSQL:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg://usuario:password@host:5432/promo_query
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
API_CORS_ORIGINS=https://tu-frontend.com
ENABLE_ADMIN_ENDPOINTS=false
```

## Fuentes bancarias

Las semillas viven en `config/bank_sources.yaml`. Ahi se configuran landings, paginas detalle, PDFs y flags basicos por banco para evitar URLs hardcodeadas dentro del scraper.

## Como recolectar

Recolectar todo:

```bash
python -m app collect --month 2026-04
```

Recolectar por banco:

```bash
python -m app collect --month 2026-04 --bank ueno
python -m app collect --month 2026-04 --bank itau
python -m app collect --month 2026-04 --bank sudameris
python -m app collect --month 2026-04 --bank continental
python -m app collect --month 2026-04 --bank bnf
```

El rerun del mismo banco y mes no duplica promociones. La persistencia elimina primero el lote de `bank + month_ref` y luego inserta el resultado actual del scraper.

## Base de datos

La persistencia ahora usa una capa compatible con SQLite y PostgreSQL.

- Local: funciona con `sqlite:///data/processed/catalog.sqlite`
- Online: prioriza PostgreSQL via `DATABASE_URL`
- El esquema se crea automaticamente al inicializar repositorio o API
- El rerun idempotente por `bank + month_ref` sigue vigente

Para una DB nueva no hace falta migracion manual pesada: al primer arranque del backend o de `collect`, las tablas necesarias se crean solas.

## Como validar que hubo carga

Ver promociones y combustibles en la DB local SQLite:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/processed/catalog.sqlite'); print('promotions', c.execute('select count(*) from promotions').fetchone()[0]); print('fuel_prices', c.execute('select count(*) from fuel_prices').fetchone()[0])"
```

Ver filas recientes de combustible:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/processed/catalog.sqlite'); print(c.execute('select brand, octane, base_price from fuel_prices order by octane, brand').fetchall())"
```

## Como consultar

```bash
python -m app query --text "que tarjeta me conviene para 95"
python -m app query --text "que tarjeta me conviene para 97"
python -m app query --text "hoy necesito comprar clavos"
python -m app query --text "quiero comprar en super"
python -m app query --text "quiero ver promos de ropa"
python -m app query --text "quiero comprar tecnologia"
python -m app query --text "quiero salir a comer"
python -m app query --text "quiero comprar en farmacia"
python -m app query --text "quiero cargar combustible"
python -m app query --text "que banco me conviene hoy"
```

Comportamiento esperado:

- Si hay promo + precio base: calcula `price_final_estimated`.
- Si hay solo promo: devuelve el match igual.
- Si hay solo precio base en combustible: devuelve `sin promocion detectada`.
- Si la promo de combustible es generica por rubro y no por estacion, el motor la expande contra los precios disponibles de 95 o 97.

## Como auditar

Smoke test rapido del dataset persistido:

```bash
python -m app audit --month 2026-04
python -m app audit --month 2026-04 --bank sudameris
python -m app audit --month 2026-04 --json
python -m app audit --month 2026-04 --query "que tarjeta me conviene para 97"
```

El reporte ahora muestra ademas:

- cobertura por categoria
- cobertura por banco y categoria
- top merchants por categoria
- categorias cubiertas y categorias debiles
- warnings como `weak_category_coverage`, `no_live_promos_for_category` y `fuel_octane_mismatch` cuando corresponda

El reporte incluye `api_readiness`:

- `ready`: combustibles ok, bancos clave con cobertura razonable y queries criticas utiles.
- `warning`: hay cobertura parcial o alguna query critica cae en fallback, pero el backend sigue siendo usable.
- `blocked`: falta combustible o faltan demasiados bancos clave; no conviene exponer API todavia.

Que mirar antes de exponer el sistema:

- bancos con `0` promociones para el mes auditado
- `fuel_prices_total` en `0`
- merchants `generic_or_missing` o `suspicious_clear` demasiado altos
- queries criticas con warning `no_live_promos_for_category`
- queries de combustible sin `price_base`
- queries amplias donde arriba predominan `low` o `fallback`
- categorias utiles con cobertura muy baja o dependientes solo de fallback

Smoke queries manuales recomendadas:

- `que tarjeta me conviene para 95`
- `que tarjeta me conviene para 97`
- `quiero comprar en super`
- `quiero ver promos de ropa`
- `quiero comprar tecnologia`
- `quiero salir a comer`
- `quiero comprar en farmacia`
- `hoy necesito comprar clavos`
- `que banco me conviene hoy`

## Exportar

```bash
python -m app export --format json
python -m app export --format csv
```

## Ejemplo de salida

```json
{
  "query": "que tarjeta me conviene para 97",
  "matches": [
    {
      "merchant": "Copetrol",
      "category": "combustible",
      "bank": "Sudameris",
      "benefit": "25% desc.",
      "ranking_score": 2661.4512,
      "price_base": 10650.0,
      "price_final_estimated": 7987.5,
      "valid_until": "2026-12-31",
      "source_url": "https://www.sudameris.com.py/beneficios",
      "explanation": "Base Copetrol 97: 10650 Gs. Beneficio 25% desc.. Final estimado: 7987.50 Gs."
    }
  ]
}
```

## Interpretacion rapida

- `merchant`: comercio o marca normalizada usada para el join.
- `merchant_normalized` puede quedar `null` si el scraper solo detecta un rubro util pero no un comercio confiable.
- `benefit`: resumen corto del beneficio detectado.
- `promo_type`: clasificacion heuristica del resultado (`bank_promo`, `generic_benefit`, `voucher`, `loyalty_reward`, `catalog_fallback`).
- `result_quality_label`: nivel de utilidad para display (`high`, `medium`, `low`, `fallback`).
- `result_quality_score`: score numerico para ordenar o filtrar vistas publicas.
- `price_base`: precio publicado del combustible si aplica.
- `price_final_estimated`: estimacion simple despues de descuento o cashback.
- `valid_until`: fin de vigencia cuando pudo extraerse.
- `explanation`: explicacion corta del ranking aplicado.

En queries amplias el motor prioriza primero resultados accionables con merchant y beneficio claros, luego promos genericas utiles, despues vouchers/canjes, y deja al final los fallbacks puros de catalogo.
Una promo puede seguir viva por rubro aunque `merchant_normalized` quede nulo; eso es preferible a persistir merchants basura o disclaimers como si fueran comercios reales.
El parser bloquea CTAs y textos de marketing como `conocer promos`, `conoce mas`, `ver mas` o `bases y condiciones` para que no terminen como merchants normalizados.
El comando `audit` ademas marca warnings cuando detecta degradacion de calidad o merchants sospechosos que conviene revisar antes de una exposicion publica.
Combustible y ferreteria son solo dos verticales del sistema: el query engine tambien intenta resolver supermercados, gastronomia, retail, indumentaria, tecnologia, hogar, salud, viajes y entretenimiento cuando hay cobertura en fuentes o en el catalogo.
Si `Ueno` vuelve a quedar en `0`, revisa el `collect` con `scraper_metrics`: `discovery_candidates_count`, `parsed_blocks_count`, `filtered_blocks_count` y `persisted_promotions_count` ayudan a distinguir si el banco no publico promos utiles o si el scraper las descubrio pero no las pudo persistir.

## API minima

Si `api_readiness` no queda en `blocked`, ya hay una base FastAPI lista para deploy en `src/api/main.py`.

Levantar local:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

O usar la config del entorno:

```bash
python -m app config
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Para plataformas tipo PaaS tambien hay un `Procfile` base.

Endpoints:

- `GET /health`
- `GET /audit?month=2026-04`
- `GET /query?text=que tarjeta me conviene para 97`
- `GET /banks?month=2026-04`
- `GET /fuel-prices?month=2026-04`
- `GET /promotions?month=2026-04&bank=Sudameris&category=combustible`
- `GET /categories?month=2026-04`
- `POST /admin/collect`
- `GET /admin/collect/status`
- `POST /admin/audit`

Ejemplos de admin minimo:

```bash
curl -X POST http://127.0.0.1:8000/admin/collect -H "Content-Type: application/json" -d "{\"month\":\"2026-04\"}"
curl http://127.0.0.1:8000/admin/collect/status
curl -X POST http://127.0.0.1:8000/admin/audit -H "Content-Type: application/json" -d "{\"month\":\"2026-04\"}"
```

`/admin/collect` corre en background y responde rapido con `status=started`, para evitar timeouts de request larga en hosting tipo Render Free.
Para saber si termino bien:

- `status=running`: sigue procesando
- `status=done`: termino y `last_result` trae resumen operativo
- `status=error`: fallo y `last_error` trae mensaje legible

El endpoint `GET /admin/collect/status` tambien expone progreso operativo para la UI:

- `progress`: porcentaje de 0 a 100
- `current_step`: etapa actual, por ejemplo `Procesando Sudameris`
- `current_bank`: banco actual si aplica
- `completed_steps` / `total_steps`: avance simple por etapas
- `last_result.bank_diagnostics`: diagnostico por banco, por ejemplo `ok`, `no_sources_discovered`, `all_blocks_filtered`

Si `ENABLE_ADMIN_ENDPOINTS=false`, esos endpoints devuelven `403`. Es la compuerta minima antes de agregar autenticacion real.

## Deploy online

Checklist minima para pasar a online:

1. Configurar `DATABASE_URL` de PostgreSQL.
2. Configurar `APP_ENV=production`.
3. Definir `API_CORS_ORIGINS`.
4. Decidir si `ENABLE_ADMIN_ENDPOINTS` queda `true` o `false`.
5. Correr `python -m app audit --month 2026-04` o `GET /audit` y verificar `api_readiness`.
6. Levantar `uvicorn api.main:app`.

Todavia no hay autenticacion. La siguiente fase natural despues de esta mini app es endurecer la experiencia web o separarla en un frontend independiente si hiciera falta.

## Web online integrada

La fase actual suma una mini app web server-rendered sobre la misma FastAPI. Se eligio esta variante porque:

- evita abrir una segunda pila de deploy ahora mismo
- mantiene una sola app para backend + web
- no duplica scraping ni ranking
- funciona bien en movil y escritorio con HTML/CSS responsive

No requiere un `NEXT_PUBLIC_API_BASE_URL` separado en esta etapa porque la web y la API corren en el mismo origen. Si mas adelante separas frontend y backend, ahi si convendra exponer una variable publica de base URL.

Vistas disponibles:

- `/` home con buscador y ejemplos rapidos
- `/search?q=...` resultados de query con filtros por banco, categoria, calidad y tipo
- `/audit-ui` vista resumida de readiness, warnings y cobertura
- `/fuel` tabla de 95/97 y recomendacion rapida
- `/promotions-ui` listado consultable de promociones
- `/ops` operaciones web para collect y audit

Flujo recomendado de uso:

1. Entrar a la home.
2. Buscar por texto libre: `quiero comprar en super`, `que tarjeta me conviene para 95`, `quiero salir a comer`.
3. Ajustar filtros si hace falta.
4. Revisar `/fuel` o `/promotions-ui` si queres explorar por tabla/listado.
5. Revisar `/audit-ui` antes de una exposicion publica o si algo se ve raro.
6. Usar `/ops` para correr `collect` o `audit` sin consola.

Arranque local web + API:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Luego abrir:

- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- [http://127.0.0.1:8000/audit-ui](http://127.0.0.1:8000/audit-ui)
- [http://127.0.0.1:8000/ops](http://127.0.0.1:8000/ops)

Build/deploy:

- no hay build separado de frontend en esta etapa
- se despliega la misma app FastAPI
- el `Procfile` ya sirve para un deploy simple tipo PaaS

Lo que todavia falta antes de una web mas completa:

- autenticacion si despues se quiere exponer admin
- una UI mas rica cliente-side si mas adelante queres interacciones sin recarga
- endurecer merchants live raros que todavia puedan aparecer en algunos resultados

## Operacion diaria sin consola

Uso diario recomendado:

1. Entrar a `/`.
2. Buscar por texto libre.
3. Filtrar si hace falta en `/search`.
4. Revisar `/fuel` para 95/97.
5. Revisar `/promotions-ui` si queres navegar el dataset cargado.
6. Entrar a `/ops` para:
   - correr `collect` del mes actual o de un banco puntual
   - correr `audit`
   - ver barra de progreso, banco actual, warnings, diagnostico por banco y resumen del ultimo resultado sin salir del navegador

Hardening web ya incluido:

- validacion de `month` en formato `YYYY-MM`
- manejo de banco invalido en formularios
- mensajes de error legibles en vez de tracebacks crudos
- estados vacios diferenciando entre:
  - sin promo real
  - solo fallback por rubro
  - filtros demasiado restrictivos

Pendientes que no bloquean uso real:

- proteger `/ops` y endpoints admin cuando llegue la fase de auth
- agregar persistencia real de historial de busquedas entre dispositivos
- seguir puliendo merchants live raros en algunas fuentes

## Tests

```bash
python -m pytest -q
```

La suite usa fixtures locales para HTML/PDF simulados y no depende de internet.
