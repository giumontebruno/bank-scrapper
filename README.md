# promo-query-py

Vitrina diaria de promociones bancarias y precios de combustibles para Paraguay.

## Que hace hoy

- Muestra una home tipo feed de `Promos de hoy`, agrupadas por categoria/rubro.
- Consulta por intencion de compra sin LLM cuando queres buscar algo puntual.
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
- `ADMIN_TOKEN`: token compartido para proteger `/ops` y endpoints `/admin/*`

Ejemplo local:

```bash
APP_ENV=local
DATABASE_URL=sqlite:///data/processed/catalog.sqlite
API_HOST=127.0.0.1
API_PORT=8000
LOG_LEVEL=INFO
API_CORS_ORIGINS=*
ENABLE_ADMIN_ENDPOINTS=true
ADMIN_TOKEN=dev-secret
```

Ejemplo online con PostgreSQL:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg://usuario:password@host:5432/promo_query
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
API_CORS_ORIGINS=https://tu-frontend.com
ENABLE_ADMIN_ENDPOINTS=true
ADMIN_TOKEN=un-token-largo-y-privado
```

## Fuentes bancarias

Las semillas viven en `config/bank_sources.yaml`. Ahi se configuran landings, paginas detalle, PDFs y flags basicos por banco para evitar URLs hardcodeadas dentro del scraper.

## Fuentes complementarias V1

Ademas de promos bancarias scrapeadas, el catalogo canonico ya acepta fuentes simples para sumar senales utiles sin reescribir scrapers:

- `manual_source`: carga manual o semimanual verificada.
- `merchant_campaign`: campania publicada por un comercio.
- `social_signal`: senal liviana desde redes u otra fuente social, pensada como contexto de baja confianza hasta verificar.

El archivo local opcional es `config/manual_offers.yaml` y no se trackea en git. Usar `config/manual_offers.example.yaml` como plantilla. Estas fuentes se convierten a `Offer` canonica y entran al feed de `Promos de hoy` con score/calidad, deduplicacion y menor prioridad si son genericas.

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
curl -X POST http://127.0.0.1:8000/admin/collect -H "Content-Type: application/json" -H "X-Admin-Token: dev-secret" -d "{\"month\":\"2026-04\"}"
curl http://127.0.0.1:8000/admin/collect/status -H "X-Admin-Token: dev-secret"
curl -X POST http://127.0.0.1:8000/admin/audit -H "Content-Type: application/json" -H "X-Admin-Token: dev-secret" -d "{\"month\":\"2026-04\"}"
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

Si `ENABLE_ADMIN_ENDPOINTS=false`, esos endpoints devuelven `403`. Si `ADMIN_TOKEN` esta configurado, los endpoints admin requieren `X-Admin-Token` o la cookie creada desde `/ops`.

## Deploy online

Checklist minima para pasar a online:

1. Configurar `DATABASE_URL` de PostgreSQL.
2. Configurar `APP_ENV=production`.
3. Definir `API_CORS_ORIGINS`.
4. Decidir si `ENABLE_ADMIN_ENDPOINTS` queda `true` o `false`.
5. Si `ENABLE_ADMIN_ENDPOINTS=true`, definir `ADMIN_TOKEN` con un valor largo y privado.
6. Correr `python -m app audit --month 2026-04` o `GET /audit` y verificar `api_readiness`.
7. Levantar `uvicorn api.main:app`.

Todavia no hay autenticacion. La siguiente fase natural despues de esta mini app es endurecer la experiencia web o separarla en un frontend independiente si hiciera falta.

## Web online integrada

La fase actual suma una mini app web server-rendered sobre la misma FastAPI. Se eligio esta variante porque:

- evita abrir una segunda pila de deploy ahora mismo
- mantiene una sola app para backend + web
- no duplica scraping ni ranking
- funciona bien en movil y escritorio con HTML/CSS responsive

No requiere un `NEXT_PUBLIC_API_BASE_URL` separado en esta etapa porque la web y la API corren en el mismo origen. Si mas adelante separas frontend y backend, ahi si convendra exponer una variable publica de base URL.

Vistas disponibles:

- `/` home con feed de `Promos de hoy`, destacados y categorias clickeables
- `/search?q=...` resultados de query con filtros por banco, categoria, calidad y tipo
- `/audit-ui` vista resumida de readiness, warnings y cobertura
- `/fuel` tabla de 95/97 y recomendacion rapida
- `/promotions-ui` listado consultable de promociones
- `/ops` operaciones web para collect y audit

Flujo recomendado de uso:

1. Entrar a la home y revisar `Promos de hoy`.
2. Navegar por categoria: supermercados, combustible, gastronomia, salud, hogar, etc.
3. Usar busqueda solo para algo puntual: `quiero comprar en super`, `que tarjeta me conviene para 95`, `quiero salir a comer`.
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

Si `ADMIN_TOKEN` esta configurado, `/ops` muestra un formulario simple de acceso y guarda una cookie segura para ese navegador. En movil tambien podes entrar una vez con `/ops?token=TU_TOKEN` para dejar la cookie configurada.

Hardening web ya incluido:

- validacion de `month` en formato `YYYY-MM`
- manejo de banco invalido en formularios
- mensajes de error legibles en vez de tracebacks crudos
- estados vacios diferenciando entre:
  - sin promo real
  - solo fallback por rubro
  - filtros demasiado restrictivos

Pendientes que no bloquean uso real:

- reemplazar token compartido por usuarios/login si mas adelante hay mas operadores
- agregar persistencia real de historial de busquedas entre dispositivos
- seguir puliendo merchants live raros en algunas fuentes

## Automatizacion diaria

El repo incluye el workflow `.github/workflows/daily-collect-audit.yml` para GitHub Actions. Corre una vez al dia y tambien se puede disparar manualmente con `workflow_dispatch`.

Flujo automatico:

1. Resuelve el mes actual en formato `YYYY-MM`.
2. Llama `POST /admin/collect` con `X-Admin-Token`.
3. Espera el fin de collect consultando `GET /admin/collect/status`.
4. Si collect termina en `done`, llama `POST /admin/audit`.
5. Si collect termina en `error` o no finaliza a tiempo, falla el workflow para que quede visible en GitHub Actions.

Secrets necesarios en GitHub:

- `PROMO_QUERY_BASE_URL`: URL publica de la app, por ejemplo `https://tu-app.onrender.com`
- `ADMIN_TOKEN`: el mismo valor configurado en Render como `ADMIN_TOKEN`

No guardes el token en README ni en codigo. Cargalo solo como secret de GitHub y variable de entorno del hosting.

Para verificar la ultima ejecucion desde la web:

- entrar a `/ops`
- revisar `status`, `finished_at`, `last_result`, `warnings` y `bank_diagnostics`
- si hace falta, abrir `/audit-ui` para mirar cobertura y warnings actuales

### Rotar token admin

Antes del uso continuo, generá un token nuevo y privado. No reutilices tokens pegados en chats, capturas o pruebas.

Dónde configurarlo:

- Render: variable `ADMIN_TOKEN`
- GitHub Actions: secret `ADMIN_TOKEN`
- GitHub Actions: secret `PROMO_QUERY_BASE_URL` con la URL publica de la app

Cómo probarlo:

```bash
curl https://TU-APP.onrender.com/admin/collect/status -H "X-Admin-Token: NUEVO_TOKEN"
```

Debe responder JSON con `status`. Sin token o con token incorrecto debe responder `403`.

### Activar workflow manual por primera vez

1. Confirmar en Render: `APP_ENV=production`, `DATABASE_URL`, `ENABLE_ADMIN_ENDPOINTS=true`, `ADMIN_TOKEN`.
2. Confirmar en GitHub Secrets: `PROMO_QUERY_BASE_URL`, `ADMIN_TOKEN`.
3. Ir a GitHub Actions > `Daily collect and audit`.
4. Ejecutar `Run workflow`; podés dejar `month` vacio para usar el mes actual.
5. Verificar que el job termine verde.
6. Entrar a `/ops` y revisar `last_result`, `finished_at` y `bank_diagnostics`.

## Mejoras recientes de UI y resultados

La web mantiene FastAPI + Jinja, pero ahora tiene una capa visual mas pulida:

- home con buscador protagonista, accesos rapidos y tarjetas de accion
- resultados con badges mas claros, banco destacado y precio final estimado resaltado
- fuel con recomendacion destacada para 95/97
- promotions y audit mantienen filtros visibles y mejor lectura responsive
- ops conserva barra de progreso, diagnostico por banco y resultado compacto

Tambien se reforzo el catalogo para categorias debiles:

- tecnologia: celulares, HP Store, Samsung, Tigo, Personal, Alemania Cell
- entretenimiento: eventos, teatro, clubes, Mbatovi
- ferreteria: repuestos, talleres, electricidad, cemento, materiales

El ranking sigue priorizando promos bancarias claras por encima de beneficios genericos, vouchers y fallback de catalogo.

## Catalogo canonico de ofertas

La base evoluciono de `scrapers -> promociones crudas -> web` a una capa intermedia:

```text
ingesta -> promociones normalizadas -> catalogo canonico de ofertas -> feed del dia -> web/api
```

La entidad canonica `Offer` vive en `src/offers/` y consolida lo que viene de `Promotion`:

- banco, merchant, categoria y fuente
- beneficio normalizado: descuento, reintegro, cuotas, mixto o desconocido
- vigencia, canales, topes y minimos cuando existen
- calidad, genericidad, category-only y candidatura a destacado
- deduplicacion logica por banco + merchant + categoria + beneficio

El feed `Promos de hoy` se construye desde esas ofertas canonicas, no desde texto bruto scrapeado. Esto deja preparado el proyecto para sumar despues fuentes como `merchant_campaign`, `social_signal` o `manual_source` sin forzar los scrapers bancarios.

## Checklist final corto

1. Hacer commit y push final.
2. Rotar `ADMIN_TOKEN` en Render.
3. Cargar el mismo `ADMIN_TOKEN` en GitHub Secrets.
4. Cargar `PROMO_QUERY_BASE_URL` en GitHub Secrets.
5. Ejecutar una vez el workflow manual.
6. Abrir `/ops` y confirmar `status=done`, `warnings` y `bank_diagnostics`.

## Tests

```bash
python -m pytest -q
```

La suite usa fixtures locales para HTML/PDF simulados y no depende de internet.
