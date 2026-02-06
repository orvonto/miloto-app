from flask import Flask, request, render_template_string
import random
from datetime import datetime, timedelta, date

app = Flask(__name__)

NUM_NUMBERS = 5
MAX_NUMBER = 39

DEFAULT_HOT = [3, 4, 19, 32, 33, 35]
DEFAULT_HOT_COUNT = 2

PAYROLL_DAYS = {14, 15, 29, 30}


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


def is_payroll_day(d: date) -> bool:
    return d.day in PAYROLL_DAYS


def monday_of_week(d: date) -> date:
    """Lunes de la misma semana (si d es jueves, devuelve lunes anterior)."""
    return d - timedelta(days=d.weekday())


def next_monday(from_date: date) -> date:
    """Siguiente lunes (si hoy es lunes, devuelve hoy)."""
    days_ahead = (0 - from_date.weekday()) % 7
    return from_date + timedelta(days=days_ahead)


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


@app.route("/", methods=["GET"])
def index():
    hot_str = request.args.get("hot", "")
    hot_count = request.args.get("hot_count", str(DEFAULT_HOT_COUNT))

    # ✅ nueva: fecha base (YYYY-MM-DD) para generar el plan
    start_str = request.args.get("start", "")  # ejemplo: 2026-02-05
    start_date = parse_date_yyyy_mm_dd(start_str)

    error = None
    try:
        hot_numbers = parse_int_list(hot_str) if hot_str else DEFAULT_HOT
    except Exception as e:
        error = str(e)
        hot_numbers = DEFAULT_HOT

    try:
        hot_count_int = int(hot_count)
    except:
        hot_count_int = DEFAULT_HOT_COUNT

    # ✅ Si no te pasan fecha, usamos HOY (y luego calculamos lunes de la semana)
    base = start_date or datetime.now().date()

    # Opción recomendada: siempre arranca desde el lunes de la semana de "base"
    start_monday = monday_of_week(base)

    # Si prefieres “siguiente lunes” sí o sí, cambia la línea anterior por:
    # start_monday = next_monday(base)

    draw_dates = build_draw_dates(start_monday)

    week1 = draw_dates[:4]
    week2 = draw_dates[4:]
    w1 = weekly_weights_for_dates(week1)
    w2 = weekly_weights_for_dates(week2)

    day_plan = [(d, w1[d]) for d in week1] + [(d, w2[d]) for d in week2]
    total_bets = sum(n for _, n in day_plan)  # 12

    combos = []
    seen = set()
    while len(combos) < total_bets:
        c = tuple(generate_combination(hot_numbers, hot_count_int))
        if c in seen:
            continue
        seen.add(c)
        combos.append(list(c))

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
    .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    input, select { padding:10px; border-radius:10px; border:1px solid #ccc; }
    button { padding:10px 14px; border:0; border-radius:10px; background:#111; color:#fff; cursor:pointer; }
    .error { background:#ffecec; border:1px solid #ffb2b2; padding:10px; border-radius:10px; color:#7a0000; }
    .hint { font-size:12px; color:#666; margin-top:6px; }
    label { font-size:12px; color:#333; display:block; margin-bottom:6px; }
    .field { min-width: 220px; }
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

  <div class="card">
    <div class="date">Configuración</div>

    <div class="row">
      <div class="field" style="flex:1; min-width:260px;">
        <label>Fecha base (puedes poner “dentro de un mes”)</label>
        <input id="startDate" type="date" value="{{ start_str|e }}">
        <div class="hint">El plan se calcula desde el lunes de esa semana.</div>
      </div>

      <div class="field" style="flex:2; min-width:260px;">
        <label>Números calientes</label>
        <input id="hotInput" name="hot" style="min-width:260px; width:100%;"
               placeholder="Números calientes (ej: 3,4,19,32,33,35)"
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
    const saveBtn = document.getElementById('saveBtn');
    const genBtn  = document.getElementById('genBtn');

    function loadSettings(){
      const savedHot = localStorage.getItem('miloto_hot');
      const savedCount = localStorage.getItem('miloto_hot_count');
      const savedStart = localStorage.getItem('miloto_start');

      if(savedHot && !hotInput.value) hotInput.value = savedHot;
      if(savedCount) hotCount.value = savedCount;

      // si el input viene vacío, usamos localStorage
      if(savedStart && (!startDate.value || startDate.value.trim().length === 0)) {
        startDate.value = savedStart;
      }

      // si sigue vacío, pon hoy
      if(!startDate.value || startDate.value.trim().length === 0){
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth()+1).padStart(2,'0');
        const dd = String(today.getDate()).padStart(2,'0');
        startDate.value = `${yyyy}-${mm}-${dd}`;
      }
    }

    function saveSettings(){
      localStorage.setItem('miloto_hot', hotInput.value);
      localStorage.setItem('miloto_hot_count', hotCount.value);
      localStorage.setItem('miloto_start', startDate.value);
    }

    function goGenerate(){
      const params = new URLSearchParams();
      if(startDate.value) params.set('start', startDate.value);
      if(hotInput.value.trim().length > 0) params.set('hot', hotInput.value.trim());
      params.set('hot_count', hotCount.value);
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

    loadSettings();
  </script>
</body>
</html>
"""

    return render_template_string(
        html,
        calendar=calendar,
        day_names=day_names,
        month_names=month_names,
        payroll_days=PAYROLL_DAYS,
        hot_str=hot_str,
        hot_count_int=hot_count_int,
        error=error,
        start_str=(start_date.isoformat() if start_date else "")
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
