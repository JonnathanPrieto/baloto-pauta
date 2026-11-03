# baloto-pauta

Dashboard de impacto de pauta Baloto: registros de Google Analytics 4, compradores nuevos del CRM, valor de vida proyectado e inversión en pauta.

- **Página:** `index.html`, publicada con GitHub Pages.
- **Datos:** `data.json`. No se edita a mano; lo regenera el flujo diario.
- **Actualización:** `.github/workflows/diario.yml` ejecuta `scripts/actualizar.py` todos los días a las 7:00 a. m. (hora Colombia). El script consulta Zoho Analytics (workspace *Zoho CRM Reports* de la organización crmbaloto) y, si hay cambios, sube el nuevo `data.json`.

Si un día Zoho no tiene datos completos del día anterior o falla la conexión, el flujo termina con error, GitHub envía un correo y la página sigue mostrando la última versión buena.

## Configuración (una sola vez)

### 1. Crear el token de Zoho

1. Entra a <https://api-console.zoho.com> con la cuenta que tiene acceso a Zoho Analytics de Baloto (crmbaloto).
2. **Add Client → Self Client → Create.** Copia el **Client ID** y el **Client Secret**.
3. En la pestaña **Generate Code**:
   - Scope: `ZohoAnalytics.data.read`
   - Time duration: 10 minutes
   - Description: `GitHub baloto-pauta`
   - Clic en **Create** y copia el código que aparece. Vence en 10 minutos.
4. Cambia ese código por un *refresh token*. Abre una terminal (o Postman) y ejecuta, reemplazando los tres valores:

   ```bash
   curl -X POST "https://accounts.zoho.com/oauth/v2/token?grant_type=authorization_code&client_id=CLIENT_ID&client_secret=CLIENT_SECRET&code=CODIGO"
   ```

   En la respuesta, copia el valor de `refresh_token`. No vence mientras no se revoque.

### 2. Guardar los secretos en GitHub

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**. Crea tres:

| Nombre | Valor |
|---|---|
| `ZOHO_CLIENT_ID` | Client ID del paso 1 |
| `ZOHO_CLIENT_SECRET` | Client Secret del paso 1 |
| `ZOHO_REFRESH_TOKEN` | refresh token del paso 1 |

### 3. Activar GitHub Pages

**Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main` / `(root)` → Save.**

En uno o dos minutos la página queda en `https://jonnathanprieto.github.io/baloto-pauta/`.

### 4. Probar la actualización

**Actions → Actualizar datos del dashboard → Run workflow.** Tarda entre 5 y 20 minutos, porque las consultas de cohortes recorren todas las apuestas. Si termina en verde, la página ya muestra los datos del día anterior.

## Qué consulta el script

| Dato | Tabla en Zoho Analytics |
|---|---|
| Registros exitosos por día, plataforma y campaña | `Registros_pauta_GA (Google Analytics 4 (GA4))` |
| Compradores nuevos, gasto del primer mes y recompra | `Apuestas All` |
| Inversión por día, plataforma, etapa y campaña | `[Baloto] Fuente de datos GA4` (filas con Fuente = Plataforma) |

Reglas principales:

- Hasta septiembre de 2026 los registros usan el evento `Registro_Exitoso`; desde octubre, `registro_exitoso_sin_contrasena`.
- Pauta = campañas `adcom_*` y medios `cpc` / `paid`.
- La recompra de un mes se mide cuando cierra el mes siguiente; mientras tanto se usa el promedio de los últimos cuatro meses medidos.
