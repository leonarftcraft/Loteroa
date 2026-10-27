import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
import flet as ft
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

# Intentar importar plyer para notificaciones nativas en Android / Windows
try:
  from plyer import notification as native_notification
  PLYER_DISPONIBLE = True
except ImportError:
  PLYER_DISPONIBLE = False

HORAS_OFICIALES = [
    '09:00 AM', '10:00 AM', '11:00 AM', '12:00 PM', '01:00 PM',
    '04:00 PM', '05:00 PM', '06:00 PM', '07:00 PM', '08:00 PM'
]
MORNING_COLS = HORAS_OFICIALES[:5]
AFTERNOON_COLS = HORAS_OFICIALES[5:]

NOMBRES_ANIMALES = {
    '01': 'Carnero', '02': 'Toro', '03': 'Ciempiés', '04': 'Alacrán',
    '05': 'León', '06': 'Rana', '07': 'Perico', '08': 'Ratón',
    '09': 'Águila', '10': 'Tigre', '11': 'Gato', '12': 'Caballo',
    '13': 'Mono', '14': 'Paloma', '15': 'Zorro', '16': 'Oso',
    '17': 'Pavo', '18': 'Burro', '19': 'Chivo', '20': 'Cochino',
    '21': 'Gallo', '22': 'Camello', '23': 'Cebra', '24': 'Iguana',
    '25': 'Gallina', '26': 'Vaca', '27': 'Perro', '28': 'Zamuro',
    '29': 'Elefante', '30': 'Caimán', '31': 'Lapa', '32': 'Ardilla',
    '33': 'Pescado', '34': 'Venado', '35': 'Jirafa', '36': 'Culebra',
    '37': 'Delfín (0)', '38': 'Ballena (00)'
}


class MotorGranjaApp:

  def __init__(self, json_path='granjamillionaria_sorteos.json'):
    self.json_path = json_path
    self.pago_loteria = 30.0
    self.dias_ventana_reciente = 250
    self.dias_max_historial = 365 * 3  # Exactamente 3 años (1,095 días)
    self.asegurar_json_base()

  def asegurar_json_base(self):
    if not os.path.exists(self.json_path):
      with open(self.json_path, 'w', encoding='utf-8') as f:
        json.dump([], f)

  @staticmethod
  def normalizar_animal(val):
    s = str(val).strip()
    if s == '0':
      return '37'
    if s == '00':
      return '38'
    return s.zfill(2)

  @staticmethod
  def normalizar_hora(h_str):
    s = str(h_str).strip().upper()
    s = s.replace('A.M.', 'AM').replace('P.M.', 'PM').replace('.', '')
    s = re.sub(r'\s+', ' ', s)
    if len(s) == 7 and s[1] == ':':  # Ej: '9:00 AM' -> '09:00 AM'
      s = '0' + s
    return s

  def cargar_dataframe(self):
    try:
      with open(self.json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    except Exception:
      data = []

    if not data:
      return pd.DataFrame(columns=['fecha', 'hora', 'resultados', 'hour_idx', 'datetime'])

    df = pd.DataFrame(data)
    df['fecha'] = df['fecha'].astype(str).str.strip()
    df['hora'] = df['hora'].apply(self.normalizar_hora)
    df['resultados'] = df['resultados'].apply(self.normalizar_animal)

    cods_validos = {f'{i:02d}' for i in range(1, 39)}
    df = df[df['resultados'].isin(cods_validos)].copy()
    df['hour_idx'] = df['hora'].map({h: i for i, h in enumerate(HORAS_OFICIALES)})
    df = df.dropna(subset=['hour_idx']).copy()
    df['hour_idx'] = df['hour_idx'].astype(int)
    df['datetime'] = pd.to_datetime(
        df['fecha'] + ' ' + df['hora'], format='%Y-%m-%d %I:%M %p', errors='coerce'
    )
    df = (
        df.dropna(subset=['datetime'])
        .drop_duplicates(subset=['fecha', 'hora'], keep='last')
        .sort_values(['datetime', 'hour_idx'])
        .reset_index(drop=True)
    )
    return df

  def guardar_nuevos_registros(self, nuevos_items):
    """Une nuevos registros con el JSON actual, recorta a 3 años y guarda."""
    df_actual = self.cargar_dataframe()
    registros_actuales = (
        df_actual[['fecha', 'hora', 'resultados']].to_dict('records')
        if not df_actual.empty else []
    )
    combinados = registros_actuales + nuevos_items
    df_comb = pd.DataFrame(combinados)
    if df_comb.empty:
      return 0

    df_comb['fecha'] = df_comb['fecha'].astype(str).str.strip()
    df_comb['hora'] = df_comb['hora'].apply(self.normalizar_hora)
    df_comb['resultados'] = df_comb['resultados'].apply(self.normalizar_animal)

    cods_validos = {f'{i:02d}' for i in range(1, 39)}
    df_comb = df_comb[
        df_comb['resultados'].isin(cods_validos)
        & df_comb['hora'].isin(HORAS_OFICIALES)
    ].copy()
    df_comb['hour_idx'] = df_comb['hora'].map(
        {h: i for i, h in enumerate(HORAS_OFICIALES)}
    )
    df_comb = (
        df_comb.drop_duplicates(subset=['fecha', 'hora'], keep='last')
        .sort_values(['fecha', 'hour_idx'])
        .reset_index(drop=True)
    )

    # Recortar estrictamente a los últimos 3 años (1,095 días) desde la fecha más reciente
    fecha_max = pd.to_datetime(df_comb['fecha'].max())
    fecha_corte = (fecha_max - timedelta(days=self.dias_max_historial)).strftime('%Y-%m-%d')
    df_comb = df_comb[df_comb['fecha'] >= fecha_corte].copy()

    salida = df_comb[['fecha', 'hora', 'resultados']].to_dict('records')
    with open(self.json_path, 'w', encoding='utf-8') as f:
      json.dump(salida, f, indent=2, ensure_ascii=False)

    return len(df_comb) - len(df_actual)

  # =========================================================================
  # SCRAPER ESPECÍFICO PARA LOTERIADEHOY.COM (RANGOS E HISTÓRICO DE 3 AÑOS)
  # =========================================================================
  def descargar_rango_loteriadehoy(self, fecha_ini_str, fecha_fin_str):
    url = f'https://loteriadehoy.com/animalito/granjamillionaria/historico/{fecha_ini_str}/{fecha_fin_str}/'
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        )
    }
    extraidos = []
    try:
      resp = requests.get(url, headers=headers, timeout=15)
      if resp.status_code != 200:
        return []

      soup = BeautifulSoup(resp.text, 'html.parser')

      # Buscador adaptable para tablas y bloques de loteriadehoy.com
      # Reconoce fechas YYYY-MM-DD o DD-MM-YYYY y empareja horas (09:00 AM..08:00 PM) con el número (0, 00, 01..36)
      texto_completo = soup.get_text(' ', strip=True)

      # Método 1: Tablas HTML estructuradas por columnas de fecha o filas de horario
      tablas = soup.find_all('table')
      for tabla in tablas:
        encabezados = [th.get_text(strip=True) for th in tabla.find_all('th')]
        fechas_col = {}
        for idx_col, texto_th in enumerate(encabezados):
          m_iso = re.search(r'(\d{4}-\d{2}-\d{2})', texto_th)
          m_lat = re.search(r'(\d{2})[-/](\d{2})[-/](\d{4})', texto_th)
          if m_iso:
            fechas_col[idx_col] = m_iso.group(1)
          elif m_lat:
            fechas_col[idx_col] = f'{m_lat.group(3)}-{m_lat.group(2)}-{m_lat.group(1)}'

        for fila in tabla.find_all('tr'):
          celdas = [td.get_text(' ', strip=True) for td in fila.find_all(['td', 'th'])]
          if not celdas:
            continue
          m_hora = re.search(r'(0?[1-9]|1[0-2]):00\s*(AM|PM|A\.M\.|P\.M\.)', celdas[0], re.I)
          if m_hora and fechas_col:
            hora_limpia = self.normalizar_hora(m_hora.group(0))
            for col_i, f_str in fechas_col.items():
              if col_i < len(celdas):
                m_num = re.search(r'\b(00|0?[0-9]|[12][0-9]|3[0-8])\b', celdas[col_i])
                if m_num:
                  extraidos.append({
                      'fecha': f_str,
                      'hora': hora_limpia,
                      'resultados': self.normalizar_animal(m_num.group(1))
                  })

      # Método 2: Tarjetas o contenedores individuales (fallback si cambia el diseño de tabla a divs)
      if not extraidos:
        bloques_fecha = re.split(r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})', texto_completo)
        fecha_actual_bloque = fecha_ini_str
        for fragmento in bloques_fecha:
          m_f1 = re.match(r'^(\d{4}-\d{2}-\d{2})$', fragmento.strip())
          m_f2 = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', fragmento.strip())
          if m_f1:
            fecha_actual_bloque = m_f1.group(1)
            continue
          elif m_f2:
            fecha_actual_bloque = f'{m_f2.group(3)}-{m_f2.group(2)}-{m_f2.group(1)}'
            continue

          pares = re.findall(
              r'((?:0?[1-9]|1[0-2]):00\s*(?:AM|PM))[^0-9]{1,25}\b(00|0?[0-9]|[12][0-9]|3[0-8])\b',
              fragmento, re.I
          )
          for h_raw, num_raw in pares:
            extraidos.append({
                'fecha': fecha_actual_bloque,
                'hora': self.normalizar_hora(h_raw),
                'resultados': self.normalizar_animal(num_raw)
            })

      return extraidos
    except Exception:
      return []

  def sincronizar_ultimos_3_anos(self, callback_progreso=None):
    """Sincroniza desde la última fecha registrada en el JSON (o hace 3 años) hasta hoy en bloques de 7 días."""
    df = self.cargar_dataframe()
    hoy_dt = datetime.now()

    if df.empty:
      fecha_cursor = hoy_dt - timedelta(days=self.dias_max_historial)
    else:
      ultima_fecha_json = datetime.strptime(df['fecha'].max(), '%Y-%m-%d')
      # Retroceder 2 días por si el último día estaba incompleto
      fecha_cursor = max(
          hoy_dt - timedelta(days=self.dias_max_historial),
          ultima_fecha_json - timedelta(days=2)
      )

    nuevos_totales = 0
    while fecha_cursor <= hoy_dt:
      fecha_fin_bloque = min(fecha_cursor + timedelta(days=6), hoy_dt + timedelta(days=5))
      f_ini_s = fecha_cursor.strftime('%Y-%m-%d')
      f_fin_s = fecha_fin_bloque.strftime('%Y-%m-%d')

      if callback_progreso:
        callback_progreso(f'Descargando bloque {f_ini_s} al {f_fin_s}...')

      datos_bloque = self.descargar_rango_loteriadehoy(f_ini_s, f_fin_s)
      if datos_bloque:
        agregados = self.guardar_nuevos_registros(datos_bloque)
        nuevos_totales += max(0, agregados)

      fecha_cursor += timedelta(days=7)
      time.sleep(0.5)

    return nuevos_totales

  # =========================================================================
  # MOTOR ESTADÍSTICO: VERIFICADOR DE SESGOS Y TOP 3 ESTRATEGIAS DEL DÍA
  # =========================================================================
  def calcular_analisis_y_top3(self, fecha_consulta=None):
    df = self.cargar_dataframe()
    if df.empty:
      return [], [], {}

    if fecha_consulta is None:
      fecha_consulta = df['fecha'].iloc[-1]

    df_hoy = df[df['fecha'] == fecha_consulta].sort_values('hour_idx')
    salidos_hoy = set(df_hoy['resultados'].tolist())
    horas_jugadas_hoy = set(df_hoy['hora'].tolist())
    dict_manana = dict(
        zip(
            df_hoy[df_hoy['hora'].isin(MORNING_COLS)]['hora'],
            df_hoy[df_hoy['hora'].isin(MORNING_COLS)]['resultados']
        )
    )

    df_hist = df[df['fecha'] < fecha_consulta].copy()
    dias_10 = df_hist.groupby('fecha').filter(lambda g: len(g) == 10)
    if len(dias_10) < 100:
      return [], [], {'fecha': fecha_consulta, 'total_sorteos': len(df)}

    piv_glob = dias_10.pivot(index='fecha', columns='hour_idx', values='resultados')
    piv_glob.columns = HORAS_OFICIALES
    piv_rec = piv_glob.iloc[-self.dias_ventana_reciente :]

    piv_term_glob = piv_glob.astype(int) % 10
    piv_term_rec = piv_rec.astype(int) % 10
    mapa_term = {t: [f'{a:02d}' for a in range(1, 39) if a % 10 == t] for t in range(10)}

    estrategias_candidatas = []
    estado_sesgos = []

    # 1. Evaluar Llaves Mañana -> Terminal Tarde en Doble Ventana (Global + Reciente 250d)
    for h_m, x_val in dict_manana.items():
      m_g = piv_glob[h_m] == x_val
      m_r = piv_rec[h_m] == x_val
      if m_g.sum() < 15:
        continue

      for h_a in AFTERNOON_COLS:
        for t in range(10):
          p_g = float((piv_term_glob.loc[m_g, h_a] == t).mean())
          p_r = float((piv_term_rec.loc[m_r, h_a] == t).mean()) if m_r.sum() >= 3 else p_g
          p_base = float((piv_term_glob[h_a] == t).mean())
          if p_base <= 0:
            continue

          z_g = (p_g - p_base) / np.sqrt(p_base * (1.0 - p_base) / m_g.sum())
          if z_g >= 2.50:
            nums_vivos = [a for a in mapa_term[t] if a not in salidos_hoy]
            if not nums_vivos:
              continue
            be = (len(nums_vivos) / self.pago_loteria) * 100.0
            roi_g = ((p_g * self.pago_loteria - len(nums_vivos)) / len(nums_vivos)) * 100.0
            roi_r = ((p_r * self.pago_loteria - len(nums_vivos)) / len(nums_vivos)) * 100.0

            activo = (roi_g >= 20.0) and (roi_r >= 15.0)
            estado_sesgos.append({
                'regla': f"Si sale '{x_val}' ({h_m}) -> Jugar Terminal {t} ({h_a})",
                'global_pct': round(p_g * 100, 1),
                'reciente_pct': round(p_r * 100, 1),
                'z_score': round(z_g, 2),
                'estado': '🟢 ACTIVO' if activo else '🔴 ENFRIADO (Pausado)'
            })

            if activo and (h_a not in horas_jugadas_hoy or len(horas_jugadas_hoy) == 10):
              ip = (z_g * 0.45) + ((p_r / p_base) * 0.35) + (roi_r / 100.0 * 0.20)
              estrategias_candidatas.append({
                  'hora': h_a,
                  'titulo': f'Terminal {t} Purgado (Llave {h_m} = {x_val})',
                  'numeros': nums_vivos,
                  'acierto_pct': round(p_g * 100, 1),
                  'reciente_pct': round(p_r * 100, 1),
                  'breakeven_pct': round(be, 1),
                  'roi_pct': round(roi_g, 1),
                  'z_score': round(z_g, 2),
                  'nivel': 'ALTA VENTAJA' if z_g >= 3.0 else 'VENTAJA MEDIA',
                  'ip': ip
              })

    # 2. Evaluar Jala-Jala Directo por Hora (Combo de 3 animales)
    for h_m, x_val in dict_manana.items():
      m_g = piv_glob[h_m] == x_val
      if m_g.sum() < 18:
        continue
      for h_a in AFTERNOON_COLS:
        vc = piv_glob.loc[m_g, h_a].value_counts()
        cands = [a for a in vc.index if a not in salidos_hoy]
        if len(cands) < 3:
          continue
        top1 = cands[0]
        p_top1 = vc[top1] / m_g.sum()
        z_top1 = (p_top1 - (1 / 38)) / np.sqrt((1 / 38) * (37 / 38) / m_g.sum())
        if vc[top1] >= 4 and z_top1 >= 3.80:
          combo3 = cands[:3]
          p_c3 = piv_glob.loc[m_g, h_a].isin(combo3).mean()
          m_r = piv_rec[h_m] == x_val
          p_c3_rec = piv_rec.loc[m_r, h_a].isin(combo3).mean() if m_r.sum() >= 3 else p_c3
          activo = p_c3_rec >= 0.25
          estado_sesgos.append({
              'regla': f"Jala-Jala '{x_val}' ({h_m}) -> Combo {combo3} ({h_a})",
              'global_pct': round(p_c3 * 100, 1),
              'reciente_pct': round(p_c3_rec * 100, 1),
              'z_score': round(z_top1, 2),
              'estado': '🟢 ACTIVO' if activo else '🔴 ENFRIADO (Pausado)'
          })
          if activo:
            roi_c3 = ((p_c3 * self.pago_loteria - 3.0) / 3.0) * 100.0
            ip = (z_top1 * 0.45) + (p_c3_rec * 3.5) + (roi_c3 / 100.0 * 0.20)
            estrategias_candidatas.append({
                'hora': h_a,
                'titulo': f'Combo 3 Jala-Jala (Disparador {h_m} = {x_val})',
                'numeros': combo3,
                'acierto_pct': round(p_c3 * 100, 1),
                'reciente_pct': round(p_c3_rec * 100, 1),
                'breakeven_pct': 10.0,
                'roi_pct': round(roi_c3, 1),
                'z_score': round(z_top1, 2),
                'nivel': 'ALTA VENTAJA',
                'ip': ip
            })

    # 3. Evaluar Motor de Rebote de Lags Activos (30, 46, 33, 16, 35, 27, 42, 54) para 05:00 PM y 08:00 PM
    lags_activos = [30, 46, 33, 16, 35, 27, 42, 54, 12]
    res_hist = df[df['fecha'] <= fecha_consulta]['resultados'].values
    ultimos_6 = set(res_hist[-6:])
    excluidos_lag = salidos_hoy.union(ultimos_6)

    for h_a, bono_h, hr_est, roi_est, z_est in [
        ('08:00 PM', 3.20, 14.5, 44.6, 4.46),
        ('05:00 PM', 2.40, 11.6, 16.0, 3.10)
    ]:
      combo_lag = []
      for lg in lags_activos:
        if len(res_hist) >= lg:
          cand = res_hist[-lg]
          if cand not in excluidos_lag and cand not in combo_lag:
            combo_lag.append(cand)
        if len(combo_lag) == 3:
          break
      if len(combo_lag) == 3:
        estrategias_candidatas.append({
            'hora': h_a,
            'titulo': f'Combo 3 Rebote de Lags + Purga Diaria ({h_a})',
            'numeros': combo_lag,
            'acierto_pct': hr_est,
            'reciente_pct': hr_est,
            'breakeven_pct': 10.0,
            'roi_pct': roi_est,
            'z_score': z_est,
            'nivel': 'ALTA VENTAJA' if h_a == '08:00 PM' else 'VENTAJA MEDIA',
            'ip': bono_h
        })

    # Ordenar por Índice de Potencia (IP) y seleccionar MÁXIMO 3 ESTRATEGIAS
    estrategias_candidatas.sort(key=lambda x: x['ip'], reverse=True)
    top_3 = []
    horas_usadas = set()
    for est in estrategias_candidatas:
      Key_unica = (est['hora'], tuple(est['numeros']))
      if Key_unica not in horas_usadas:
        top_3.append(est)
        horas_usadas.add(Key_unica)
      if len(top_3) == 3:
        break

    resumen_meta = {
        'fecha': fecha_consulta,
        'total_sorteos': len(df),
        'dias_completos': len(piv_glob),
        'salidos_hoy': list(df_hoy['resultados'].values)
    }
    return top_3, estado_sesgos, resumen_meta


# =============================================================================
# INTERFAZ GRÁFICA HÍBRIDA (FLET: ANDROID APK + WINDOWS EXE)
# =============================================================================
def main(page: ft.Page):
  page.title = 'Granja Millonaria Pro - Analizador Cuántico'
  page.theme_mode = ft.ThemeMode.DARK
  page.padding = 12
  page.window_width = 430
  page.window_height = 840

  motor = MotorGranjaApp()

  def disparar_notificacion(titulo, mensaje):
    """Envía notificación nativa al sistema (Android/Windows) y alerta en la App."""
    if PLYER_DISPONIBLE:
      try:
        native_notification.notify(
            title=titulo, message=mensaje, app_name='Granja Millonaria Pro', timeout=10
        )
      except Exception:
        pass
    page.snack_bar = ft.SnackBar(
        content=ft.Text(f'🔔 {titulo}: {mensaje}', weight=ft.FontWeight.BOLD),
        bgcolor=ft.colors.GREEN_800
    )
    page.snack_bar.open = True
    page.update()

  # Contenedores de las 3 pestañas
  col_top3 = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=10)
  col_historial = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=8)
  col_sesgos = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=8)
  txt_estado_sync = ft.Text('🟢 Sincronizado con JSON local', size=12, color=ft.colors.GREEN_400)

  # Selector de fecha para el módulo de Resultados Descargados
  df_init = motor.cargar_dataframe()
  ultima_fecha_disp = df_init['fecha'].iloc[-1] if not df_init.empty else datetime.now().strftime('%Y-%m-%d')
  input_fecha_hist = ft.TextField(
      label='Buscar Fecha (YYYY-MM-DD)',
      value=ultima_fecha_disp,
      width=220,
      height=48,
      text_size=14
  )

  def renderizar_todo(fecha_hist_especifica=None):
    df = motor.cargar_dataframe()
    if df.empty:
      return

    fecha_ult = df['fecha'].iloc[-1]
    top3, lista_sesgos, meta = motor.calcular_analisis_y_top3(fecha_ult)

    # 1. Renderizar Pestaña 1: TOP 3 ESTRATEGIAS DEL DÍA
    col_top3.controls.clear()
    col_top3.controls.append(
        ft.Container(
            padding=12,
            border_radius=10,
            bgcolor=ft.colors.BLUE_GREY_900,
            content=ft.Column([
                ft.Text(f"📅 JUGADAS RECOMENDADAS ({meta.get('fecha', '')})", size=16, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"Base activa: {meta.get('total_sorteos', 0):,} sorteos (3 años) | "
                    f"Salidos hoy (Purgados): {', '.join(meta.get('salidos_hoy', []))}",
                    size=12, color=ft.colors.GREY_300
                )
            ])
        )
    )

    if not top3:
      col_top3.controls.append(ft.Text('Esperando sorteos de la mañana para activar las 3 estrategias...'))
    else:
      for idx, est in enumerate(top3, start=1):
        nums_detalle = '  •  '.join([f"[{n}] {NOMBRES_ANIMALES.get(n, '')}" for n in est['numeros']])
        color_borde = ft.colors.GREEN_500 if est['nivel'] == 'ALTA VENTAJA' else ft.colors.AMBER_500
        col_top3.controls.append(
            ft.Container(
                padding=14,
                border_radius=12,
                bgcolor=ft.colors.GREY_900,
                border=ft.border.all(2, color_borde),
                content=ft.Column([
                    ft.Row([
                        ft.Text(f'ESTRATEGIA #{idx} — HORA: {est["hora"]}', size=15, weight=ft.FontWeight.BOLD, color=color_borde),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            border_radius=6,
                            bgcolor=color_borde,
                            content=ft.Text(est['nivel'], size=10, color=ft.colors.BLACK, weight=ft.FontWeight.BOLD)
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(est['titulo'], size=12, color=ft.colors.GREY_400),
                    ft.Divider(height=8),
                    ft.Text('JUGAR ESTOS NÚMEROS:', size=11, color=ft.colors.GREEN_300),
                    ft.Text(nums_detalle, size=15, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                    ft.Divider(height=8),
                    ft.Row([
                        ft.Text(f"Acierto: {est['acierto_pct']}% (Eq: {est['breakeven_pct']}%)", size=12),
                        ft.Text(f"Z: +{est['z_score']}", size=12, weight=ft.FontWeight.BOLD),
                        ft.Text(f"ROI (30x): +{est['roi_pct']}%", size=12, color=ft.colors.GREEN_400, weight=ft.FontWeight.BOLD)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ])
            )
        )

    # 2. Renderizar Pestaña 2: MÓDULO DE RESULTADOS DESCARGADOS
    col_historial.controls.clear()
    f_buscar = fecha_hist_especifica if fecha_hist_especifica else input_fecha_hist.value.strip()
    df_dia_sel = df[df['fecha'] == f_buscar].sort_values('hour_idx')

    fechas_recientes = sorted(df['fecha'].unique(), reverse=True)[:15]
    chips_fechas = ft.Row(
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.ElevatedButton(
                text=f_d,
                on_click=lambda e, f_val=f_d: cambiar_fecha_historial(f_val),
                bgcolor=ft.colors.BLUE_800 if f_d == f_buscar else ft.colors.GREY_800
            ) for f_d in fechas_recientes
        ]
    )

    col_historial.controls.append(
        ft.Column([
            ft.Text(f'📂 BASE DE DATOS LOCAL ({len(df):,} sorteos en ventana de 3 años)', size=15, weight=ft.FontWeight.BOLD),
            ft.Row([
                input_fecha_hist,
                ft.ElevatedButton('Ver Día', icon=ft.icons.SEARCH, on_click=lambda _: renderizar_todo(input_fecha_hist.value))
            ]),
            ft.Text('Últimas fechas descargadas:', size=12, color=ft.colors.GREY_400),
            chips_fechas,
            ft.Divider()
        ])
    )

    if df_dia_sel.empty:
      col_historial.controls.append(ft.Text(f'No hay resultados guardados para la fecha {f_buscar}.', color=ft.colors.RED_300))
    else:
      for _, fila in df_dia_sel.iterrows():
        cod = fila['resultados']
        nom = NOMBRES_ANIMALES.get(cod, '')
        col_historial.controls.append(
            ft.Container(
                padding=10,
                border_radius=8,
                bgcolor=ft.colors.BLUE_GREY_900,
                content=ft.Row([
                    ft.Text(f"🕒 {fila['hora']}", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f'[{cod}] {nom}', size=15, weight=ft.FontWeight.BOLD, color=ft.colors.AMBER_300),
                    ft.Text(f'Terminal {int(cod)%10}', size=12, color=ft.colors.GREY_400)
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            )
        )

    # 3. Renderizar Pestaña 3: MONITOR DE SESGOS ACTIVOS VS ENFRIADOS
    col_sesgos.controls.clear()
    col_sesgos.controls.append(
        ft.Text('🔍 AUDITORÍA DE VIGENCIA (HISTÓRICO 3 AÑOS vs ÚLTIMOS 250 DÍAS)', size=15, weight=ft.FontWeight.BOLD)
    )
    for s in lista_sesgos:
      col_sesgos.controls.append(
          ft.Container(
              padding=10,
              border_radius=8,
              bgcolor=ft.colors.GREY_900,
              content=ft.Column([
                  ft.Row([
                      ft.Text(s['regla'], size=12, weight=ft.FontWeight.BOLD, expand=True),
                      ft.Text(s['estado'], size=11, weight=ft.FontWeight.BOLD)
                  ]),
                  ft.Text(
                      f"Global (3 años): {s['global_pct']}%  |  Reciente (250d): {s['reciente_pct']}%  |  Z = +{s['z_score']}",
                      size=11, color=ft.colors.GREY_400
                  )
              ])
          )
      )

    page.update()

  def cambiar_fecha_historial(nueva_f):
    input_fecha_hist.value = nueva_f
    renderizar_todo(nueva_f)

  def accion_sincronizar_manual(_):
    txt_estado_sync.value = '⏳ Conectando a loteriadehoy.com...'
    page.update()

    def tarea():
      def prog(msg):
        txt_estado_sync.value = f'⏳ {msg}'
        page.update()

      nuevos = motor.sincronizar_ultimos_3_anos(callback_progreso=prog)
      df_n = motor.cargar_dataframe()
      if not df_n.empty:
        input_fecha_hist.value = df_n['fecha'].iloc[-1]
      txt_estado_sync.value = f'🟢 Actualizado ({nuevos} sorteos nuevos añadidos)'
      renderizar_todo()
      if nuevos > 0:
        top3, _, _ = motor.calcular_analisis_y_top3()
        if top3:
          mejor = top3[0]
          disparar_notificacion(
              f"Nuevos resultados ({mejor['hora']})",
              f"Jugar: {', '.join(mejor['numeros'])} (ROI +{mejor['roi_pct']}%)"
          )

    threading.Thread(target=tarea, daemon=True).start()

  # Demonio automático que revisa cada minuto si son las XX:10 (10 minutos después del sorteo)
  def reloj_automatico_10_min():
    horas_disparo = {'09:10', '10:10', '11:10', '12:10', '13:10', '16:10', '17:10', '18:10', '19:10', '20:10'}
    ultimo_minuto_ejecutado = ''
    while True:
      ahora_str = datetime.now().strftime('%H:%M')
      if ahora_str in horas_disparo and ahora_str != ultimo_minuto_ejecutado:
        ultimo_minuto_ejecutado = ahora_str
        accion_sincronizar_manual(None)
      time.sleep(25)

  threading.Thread(target=reloj_automatico_10_min, daemon=True).start()

  # Barra superior fija
  barra_superior = ft.Container(
      padding=8,
      bgcolor=ft.colors.BLUE_GREY_900,
      border_radius=8,
      content=ft.Row([
          txt_estado_sync,
          ft.ElevatedButton('Sincronizar Web', icon=ft.icons.SYNC, on_click=accion_sincronizar_manual)
      ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
  )

  cuerpo_principal = ft.Container(content=col_top3, expand=True)

  def cambiar_pestana(e):
    idx = e.control.selected_index
    if idx == 0:
      cuerpo_principal.content = col_top3
    elif idx == 1:
      cuerpo_principal.content = col_historial
    else:
      cuerpo_principal.content = col_sesgos
    page.update()

  page.navigation_bar = ft.NavigationBar(
      selected_index=0,
      on_change=cambiar_pestana,
      destinations=[
          ft.NavigationDestination(icon=ft.icons.STAR, label='Top 3 Hoy'),
          ft.NavigationDestination(icon=ft.icons.HISTORY, label='Resultados (3 Años)'),
          ft.NavigationDestination(icon=ft.icons.ANALYTICS, label='Sesgos Activos')
      ]
  )

  page.add(barra_superior, cuerpo_principal)
  renderizar_todo()


if __name__ == '__main__':
  ft.app(target=main)
