from flask import Flask, request, render_template_string
import random
from datetime import datetime, timedelta, date
import csv
import io
import urllib.request

app = Flask(__name__)

NUM_NUMBERS = 5
MAX_NUMBER = 39

DEFAULT_HOT = [3, 4, 19, 32, 33, 35]
DEFAULT_HOT_COUNT = 2

PAYROLL_DAYS = {14, 15, 29, 30}

# ✅ Tus links por defecto (los que me pasaste)
DEFAULT_SORTEOS_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTy9U4tfHkyG-DmVoCIBWAub5xFPRGH9Di1jDIM3dcNFMpyjfN4yNetJOUf8oGZ1c2zNJbeq0-7pCtv/pub?gid=1014698381&single=true&output=csv"
DEFAULT_JUGADAS_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTy9U4tfHkyG-DmVoCIBWAub5xFPRGH9Di1jDIM3dcNFMpyjfN4yNetJOUf8oGZ1c2zNJbeq0-7pCtv/pub?gid=1636174563&single=true&output=csv"


def parse_int_list(s: str):
    """Parsea '3, 7,10  11' -> [3,7,10,11] validando 1..39, únicos."""
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",")]
    nums = []
    for p in parts:
        if not p:
            continue
        if not p.isdigit():
            raise ValueError("Solo se permiten números separados por comas.")
        n = int(p)
        if n < 1 or n > MAX_NUMBER:
            raise ValueError(f"Número fuera de rango (1..{MAX_NUMBER}): {n}")
        nums.append(n)

    seen = set()
    out = []
    for n in nums:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def parse_date_yyyy_mm_dd(s: str) -> date | None:
    """Parsea '2026-02-05' -> date. Devuelve None si viene vacío."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except:
        return None


def parse_date_flexible(s: str) -> date | None:
    """Acepta '2026-02-03' o '03/02/2026'."""
    if not s:
        return None
    s = str(s).strip()
    fmts = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except:
            pass
    return None


def is_payroll_day(d: date) -> bool:
    return d.day in PAYROLL_DAYS


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_draw_dates(start_monday: date):
    """8 fechas de sorteos: lun, mar, jue, vie por 2 semanas."""
    draw_weekdays = {0, 1, 3, 4}
    dates = []
    d = start_monday
    while len(dates) < 8:
        if d.weekday() in draw_weekdays:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def weekly_weights_for_dates(week_dates):
    """
    Regla base por semana: Lunes 2, Martes 1, Jueves 1, Viernes 2 = 6.
    Ajuste: si lunes/viernes cae en día 14–15 o 29–30, mueve 1 apuesta extra a martes/jueves (si no es nómina).
    """
    wd = {d.weekday(): d for d in week_dates}
    monday = wd[0]
    tuesday = wd[1]
    thursday = wd[3]
    friday = wd[4]
    weights = {monday: 2, tuesday: 1, thursday: 1, friday: 2}

    def move_extra(from_day, candidates):
        if weights[from_day] < 2:
            return
        for c in candidates:
            if not is_payroll_day(c):
                weights[from_day] -= 1
                weights[c] += 1
                return

    if is_payroll_day(monday):
        move_extra(monday, [tuesday, thursday])

    if is_payroll_day(friday):
        move_extra(friday, [tuesday, thursday])

    if sum(weights.values()) != 6:
        weights = {monday: 2, tuesday: 1, thursday: 1, friday: 2}

    return weights


def generate_combination(hot_numbers, hot_count):
    """Genera 1 combinación válida usando hot_numbers y hot_count (0..3)."""
    all_nums = list(range(1, MAX_NUMBER + 1))
    hot_numbers = [n for n in hot_numbers if 1 <= n <= MAX_NUMBER]
    hot_set = set(hot_numbers)
    non_hot = [n for n in all_nums if n not in hot_set]

    hot_count = max(0, min(int(hot_count), 3))
    hot_count = min(hot_count, len(hot_numbers))

    while True:
        comb = set()

        if hot_count > 0:
            comb.update(random.sample(hot_numbers, hot_count))

        needed = NUM_NUMBERS - len(comb)
        pool = non_hot if len(non_hot) >= needed else all_nums
        comb.update(random.sample(pool, needed))

        comb_list = sorted(comb)
        if len(comb_list) != NUM_NUMBERS:
            continue

        evens = sum(1 for n in comb_list if n % 2 == 0)
        if evens in (0, 5):
            continue

        lows = sum(1 for n in comb_list if n <= 19)
        if lows in (0, 5):
            continue

        longest = 1
        run = 1
        for i in range(1, len(comb_list)):
            if comb_list[i] == comb_list[i - 1] + 1:
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        if longest >= 3:
            continue

        if max(comb_list) <= 31:
            continue

        s = sum(comb_list)
        if s < 50 or s > 150:
            continue

        return comb_list


# ---------- Google Sheets CSV helpers ----------

def fetch_csv_rows(url: str, timeout=10):
    """Descarga CSV y devuelve lista de dicts (usa header)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(data))
    return list(reader)


def safe_int(x):
    try:
        return int(str(x).strip())
    except:
        return None


def compute_hot_from_history(sorteos_url: str, jugadas_url: str, top_n: int = 6, min_played: int = 1):
    """
    Opción C:
    - Frecuencia real por número desde sorteos (N1..N5)
    - Veces jugado por número desde jugadas (J1..J5)
    - ratio = freq / played (si played>0)
    - score suavizado = (freq+1)/(played+2) para evitar trampas por muestras pequeñas
    """
    # init
    freq = {n: 0 for n in range(1, MAX_NUMBER + 1)}
    played = {n: 0 for n in range(1, MAX_NUMBER + 1)}

    # --- sorteos ---
    sorteos_rows = fetch_csv_rows(sorteos_url)
    for r in sorteos_rows:
        # esperamos fecha_iso, N1..N5
        for k in ["N1", "N2", "N3", "N4", "N5"]:
            n = safe_int(r.get(k, ""))
            if n and 1 <= n <= MAX_NUMBER:
                freq[n] += 1

    # --- jugadas ---
    jugadas_rows = fetch_csv_rows(jugadas_url)
    for r in jugadas_rows:
        # esperamos FECHA, J1..J5
        for k in ["J1", "J2", "J3", "J4", "J5"]:
            n = safe_int(r.get(k, ""))
            if n and 1 <= n <= MAX_NUMBER:
                played[n] += 1

    # armar tabla
    stats = []
    for n in range(1, MAX_NUMBER + 1):
        f = freq[n]
        p = played[n]
        ratio = (f / p) if p > 0 else 0.0
        score = (f + 1) / (p + 2)  # suavizado
        stats.append({
            "n": n,
            "freq": f,
            "played": p,
            "ratio": ratio,
            "score": score
        })

    # ordenar por score, pero evitando números con 0 jugadas si min_played>0
    filtered = [x for x in stats if x["played"] >= min_played] if min_played > 0 else stats[:]
    filtered.sort(key=lambda x: (x["score"], x["freq"]), reverse=True)

    # si no hay suficientes, completamos con los más frecuentes (para no quedarte corto)
    suggested = [x["n"] for x in filtered[:top_n]]
    if len(suggested) < top_n:
        remaining = [x for x in stats if x["n"] not in suggested]
        remaining.sort(key=lambda x: x["freq"], reverse=True)
        for x in remaining:
            suggested.append(x["n"])
            if len(suggested) >= top_n:
                break

    # top table (para mostrar en pantalla)
    top_table = filtered[:max(top_n, 10)]
    return suggested, stats, top_table


@app.route("/", methods=["GET"])
def index():
    # UI params
    hot_str = request.args.get("hot", "")
    hot_count = request.args.get("hot_count", str(DEFAULT_HOT_COUNT))

    start_str = request.args.get("start", "")  # YYYY-MM-DD
    start_date = parse_date_yyyy_mm_dd(start_str)

    # Sheets params
    sorteos_url = request.args.get("sorteos_csv", DEFAULT_SORTEOS_CSV).strip()
    jugadas_url = request.args.get("jugadas_csv", DEFAULT_JUGADAS_CSV).strip()
    top_n = request.args.get("topn", "6")
    min_played = request.args.get("min_played", "1")
    use_suggested = request.args.get("use_suggested", "0")  # 1 = usar sugeridos para rellenar hot

    # parse ints
    try:
        hot_count_int = int(hot_count)
    except:
        hot_count_int = DEFAULT_HOT_COUNT

    try:
        top_n_int = max(3, min(int(top_n), 12))
    except:
        top_n_int = 6

    try:
        min_played_int = max(0, min(int(min_played), 50))
    except:
        min_played_int = 1

    error = None
    sheets_error = None
    suggested_hot = None
    hot_stats_table = None  # top preview

    # --- if user requested suggested hot ---
    if use_suggested == "1":
        try:
            suggested_hot, all_stats, top_table = compute_hot_from_history(
                sorteos_url=sorteos_url,
                jugadas_url=jugadas_url,
                top_n=top_n_int,
                min_played=min_played_int
            )
            hot_stats_table = top_table
            hot_str = ", ".join(str(x) for x in suggested_hot)  # rellenar input
        except Exception as e:
            sheets_error = f"No pude leer/parsear tus CSV: {e}"

    # --- parse hot numbers (manual o sugeridos) ---
    try:
        hot_numbers = parse_int_list(hot_str) if hot_str else DEFAULT_HOT
    except Exception as e:
        error = str(e)
        hot_numbers = DEFAULT_HOT

    # base date
    base = start_date or datetime.now().date()
    start_monday = monday_of_week(base)

    draw_dates = build_draw_dates(start_monday)

    week1 = draw_dates[:4]
    week2 = draw_dates[4:]
    w1 = weekly_weights_for_dates(week1)
    w2 = weekly_weights_for_dates(week2)

    day_plan = [(d, w1[d]) for d in week1] + [(d, w2[d]) for d in week2]
    total_bets = sum(n for _, n in day_plan)  # 12

    # combos
    combos = []
    seen = set()
    while len(combos) < total_bets:
        c = tuple(generate_combination(hot_numbers, hot_count_int))
        if c in seen:
            continue
        seen.add(c)
        combos.append(list(c))

    # calendar
    calendar = []
    idx = 0
    for d, n in day_plan:
        assigned = combos[idx: idx + n]
        idx += n
        calendar.append((d, n, assigned))

    day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    month_names = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                   "septiembre", "octubre", "noviembre", "diciembre"]

    html = """
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MiLoto — Plan Quincenal</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 18px; background: #f5f6f7; }
    h1 { margin: 0 0 10px 0; }
    .card { background:#fff; border-radius:12px; padding:14px; margin:10px 0; }
    .date { font-weight:700; margin-bottom:8px; }
    .tag { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; background:#eef; margin-left:8px; }
    .combo { margin:6px 0; font-size:16px; }
    .note { font-size:13px; color:#444; margin:10px 0; line-height:1.35; }
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; }
    input, select { padding:10px; border-radius:10px; border:1px solid #ccc; }
    button { padding:10px 14px; border:0; border-radius:10px; background:#111; color:#fff; cursor:pointer; }
    .error { background:#ffecec; border:1px solid #ffb2b2; padding:10px; border-radius:10px; color:#7a0000; }
    .warn { background:#fff7e6; border:1px solid #ffd38a; padding:10px; border-radius:10px; color:#6b4300; }
    .hint { font-size:12px; color:#666; margin-top:6px; }
    label { font-size:12px; color:#333; display:block; margin-bottom:6px; }
    .field { min-width: 220px; }
    .small { font-size:12px; color:#555; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; font-size: 13px; }
    th { font-weight: 700; }
    .muted { color:#777; }
  </style>
</head>
<body>
  <h1>MiLoto — Plan quincenal (12 apuestas)</h1>

  <div class="note">
    Regla: dobles en <b>lunes</b> y <b>viernes</b>. Si caen en 14–15 o 29–30, movemos el “extra” a martes/jueves para reducir competencia.
  </div>

  {% if error %}
    <div class="error"><b>Error en tus números calientes:</b> {{ error }}</div>
  {% endif %}

  {% if sheets_error %}
    <div class="warn"><b>Google Sheets:</b> {{ sheets_error }}</div>
  {% endif %}

  <div class="card">
    <div class="date">Configuración</div>

    <div class="row">
      <div class="field" style="flex:1; min-width:220px;">
        <label>Fecha base</label>
        <input id="startDate" type="date" value="{{ start_str|e }}">
        <div class="hint">El plan se calcula desde el lunes de esa semana.</div>
      </div>

      <div class="field" style="flex:2; min-width:260px;">
        <label>Números calientes</label>
        <input id="hotInput" name="hot" style="min-width:260px; width:100%;"
               placeholder="Ej: 3,4,19,32,33,35"
               value="{{ hot_str|e }}">
      </div>

      <div class="field">
        <label>Hot por jugada</label>
        <select id="hotCount" name="hot_count">
          {% for k in [0,1,2,3] %}
            <option value="{{k}}" {% if k == hot_count_int %}selected{% endif %}>
              {{k}} caliente(s) por jugada
            </option>
          {% endfor %}
        </select>
      </div>

      <button id="saveBtn" type="button">💾 Guardar</button>
      <button id="genBtn" type="button">⚡ Generar plan</button>
    </div>

    <div class="note">
      ✅ Se guarda en tu navegador (celular/PC) usando LocalStorage.<br>
      Si cambias de navegador, tendrás que volver a poner la lista.
    </div>
  </div>

  <div class="card">
    <div class="date">Historial (Google Sheets) → sugerir hot (opción C)</div>

    <div class="row">
      <div class="field" style="flex:2; min-width:260px;">
        <label>CSV Sorteos (EXPORT_SORTEOS)</label>
        <input id="sorteosCsv" style="width:100%;" value="{{ sorteos_url|e }}">
      </div>

      <div class="field" style="flex:2; min-width:260px;">
        <label>CSV Jugadas (JUGADAS)</label>
        <input id="jugadasCsv" style="width:100%;" value="{{ jugadas_url|e }}">
      </div>

      <div class="field">
        <label>Top hot sugeridos</label>
        <select id="topN">
          {% for k in [3,4,5,6,7,8,9,10,11,12] %}
            <option value="{{k}}" {% if k == top_n_int %}selected{% endif %}>{{k}}</option>
          {% endfor %}
        </select>
      </div>

      <div class="field">
        <label>Mín. veces jugado</label>
        <select id="minPlayed">
          {% for k in [0,1,2,3,5,8,10] %}
            <option value="{{k}}" {% if k == min_played_int %}selected{% endif %}>{{k}}</option>
          {% endfor %}
        </select>
      </div>

      <button id="suggestBtn" type="button">📥 Sugerir hot</button>
    </div>

    <div class="small muted" style="margin-top:8px;">
      * La app se actualiza sola con tus datos del Sheet al recargar. Render Free puede “dormirse” y tardar unos segundos en despertar.
    </div>

    {% if hot_stats_table %}
      <div style="margin-top:12px;">
        <div class="small"><b>Top sugerencias (score suavizado = (freq+1)/(jugado+2))</b></div>
        <table style="margin-top:6px;">
          <thead>
            <tr>
              <th>Número</th>
              <th>Frecuencia</th>
              <th>Veces jugado</th>
              <th>Ratio salida/jugado</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {% for r in hot_stats_table %}
              <tr>
                <td><b>{{ r.n }}</b></td>
                <td>{{ r.freq }}</td>
                <td>{{ r.played }}</td>
                <td>{{ "%.3f"|format(r.ratio) }}</td>
                <td>{{ "%.3f"|format(r.score) }}</td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    {% endif %}
  </div>

  {% for d, n, combos in calendar %}
    <div class="card">
      <div class="date">
        {{ day_names[d.weekday()] }} {{ d.day }} de {{ month_names[d.month-1] }} de {{ d.year }}
        {% if d.day in payroll_days %}
          <span class="tag">posible alta compra</span>
        {% endif %}
        <span class="tag">{{ n }} apuesta(s)</span>
      </div>
      {% for c in combos %}
        <div class="combo">➡️ <b>{{ c|join(' - ') }}</b></div>
      {% endfor %}
    </div>
  {% endfor %}

  <div class="note">
    Importante: en MiLoto el orden no importa; ganas si tus 5 números coinciden con los 5 del sorteo.
  </div>

  <script>
    const hotInput = document.getElementById('hotInput');
    const hotCount = document.getElementById('hotCount');
    const startDate = document.getElementById('startDate');
    const sorteosCsv = document.getElementById('sorteosCsv');
    const jugadasCsv = document.getElementById('jugadasCsv');
    const topN = document.getElementById('topN');
    const minPlayed = document.getElementById('minPlayed');

    const saveBtn = document.getElementById('saveBtn');
    const genBtn  = document.getElementById('genBtn');
    const suggestBtn = document.getElementById('suggestBtn');

    function loadSettings(){
      const savedHot = localStorage.getItem('miloto_hot');
      const savedCount = localStorage.getItem('miloto_hot_count');
      const savedStart = localStorage.getItem('miloto_start');
      const savedSorteos = localStorage.getItem('miloto_sorteos_csv');
      const savedJugadas = localStorage.getItem('miloto_jugadas_csv');
      const savedTopN = localStorage.getItem('miloto_topn');
      const savedMinPlayed = localStorage.getItem('miloto_min_played');

      if(savedHot && !hotInput.value) hotInput.value = savedHot;
      if(savedCount) hotCount.value = savedCount;

      if(savedStart && (!startDate.value || startDate.value.trim().length === 0)) {
        startDate.value = savedStart;
      }
      if(!startDate.value || startDate.value.trim().length === 0){
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth()+1).padStart(2,'0');
        const dd = String(today.getDate()).padStart(2,'0');
        startDate.value = `${yyyy}-${mm}-${dd}`;
      }

      if(savedSorteos && (!sorteosCsv.value || sorteosCsv.value.trim().length === 0)) sorteosCsv.value = savedSorteos;
      if(savedJugadas && (!jugadasCsv.value || jugadasCsv.value.trim().length === 0)) jugadasCsv.value = savedJugadas;
      if(savedTopN) topN.value = savedTopN;
      if(savedMinPlayed) minPlayed.value = savedMinPlayed;
    }

    function saveSettings(){
      localStorage.setItem('miloto_hot', hotInput.value);
      localStorage.setItem('miloto_hot_count', hotCount.value);
      localStorage.setItem('miloto_start', startDate.value);
      localStorage.setItem('miloto_sorteos_csv', sorteosCsv.value);
      localStorage.setItem('miloto_jugadas_csv', jugadasCsv.value);
      localStorage.setItem('miloto_topn', topN.value);
      localStorage.setItem('miloto_min_played', minPlayed.value);
    }

    function goGenerate(extraParams = {}){
      const params = new URLSearchParams();

      if(startDate.value) params.set('start', startDate.value);
      if(hotInput.value.trim().length > 0) params.set('hot', hotInput.value.trim());
      params.set('hot_count', hotCount.value);

      if(sorteosCsv.value.trim().length > 0) params.set('sorteos_csv', sorteosCsv.value.trim());
      if(jugadasCsv.value.trim().length > 0) params.set('jugadas_csv', jugadasCsv.value.trim());
      params.set('topn', topN.value);
      params.set('min_played', minPlayed.value);

      for (const [k,v] of Object.entries(extraParams)) {
        params.set(k, v);
      }

      window.location = '/?' + params.toString();
    }

    saveBtn.addEventListener('click', () => {
      saveSettings();
      alert('Listo: guardado en tu navegador ✅');
    });

    genBtn.addEventListener('click', () => {
      saveSettings();
      goGenerate();
    });

    suggestBtn.addEventListener('click', () => {
      saveSettings();
      // use_suggested=1 hará que el servidor lea CSV y rellene hotInput
      goGenerate({use_suggested: "1"});
    });

    loadSettings();
  </script>
</body>
</html>
"""

    # adaptar hot_stats_table para jinja (dict -> obj-like)
    class RowObj:
        def __init__(self, d):
            self.__dict__.update(d)

    hot_stats_table_obj = [RowObj(x) for x in hot_stats_table] if hot_stats_table else None

    return render_template_string(
        html,
        calendar=calendar,
        day_names=day_names,
        month_names=month_names,
        payroll_days=PAYROLL_DAYS,
        hot_str=hot_str,
        hot_count_int=hot_count_int,
        error=error,
        start_str=(start_date.isoformat() if start_date else ""),
        sorteos_url=sorteos_url,
        jugadas_url=jugadas_url,
        top_n_int=top_n_int,
        min_played_int=min_played_int,
        sheets_error=sheets_error,
        hot_stats_table=hot_stats_table_obj
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
