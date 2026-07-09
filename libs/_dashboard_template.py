"""HTML/CSS/JS template for market_dashboard.build_dashboard().

Kept separate so market_dashboard.py stays readable. The placeholders
`/*__PAYLOAD__*/`, `<!--__PLOTLY__-->` and `__TITLE__` are filled by the caller.
All charts are built client-side from the embedded PAYLOAD, so the file is fully
self-contained apart from the Plotly.js script tag.
"""

TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<!--__PLOTLY__-->
<style>
  :root{
    --bg:#0a0e13; --panel:#10161e; --panel-2:#0d131b; --edge:rgba(255,255,255,.08);
    --edge-2:rgba(255,255,255,.05); --ink:#e6edf3; --ink-2:#aeb8c4; --ink-3:#6b7785;
    --accent:#f0b35e; --good:#5ef0a8; --bad:#f05e8a;
    --mono:'IBM Plex Mono',ui-monospace,monospace;
    --disp:'Space Grotesk',system-ui,sans-serif;
    --body:'Inter',system-ui,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:
        radial-gradient(900px 480px at 80% -10%, rgba(240,179,94,.06), transparent 60%),
        var(--bg);
    color:var(--ink); font-family:var(--body); font-size:14px; line-height:1.5;
    -webkit-font-smoothing:antialiased;}
  a{color:inherit}
  .wrap{max-width:1320px; margin:0 auto; padding:26px 22px 80px}

  /* ---- header ---- */
  header{display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:space-between;
    gap:14px; padding-bottom:18px; border-bottom:1px solid var(--edge);}
  .brand{display:flex; flex-direction:column; gap:4px}
  .eyebrow{font-family:var(--mono); font-size:11px; letter-spacing:.32em; text-transform:uppercase;
    color:var(--ink-3)}
  h1{font-family:var(--disp); font-weight:700; font-size:26px; letter-spacing:-.01em; margin:0}
  .sub{color:var(--ink-2); font-size:13px}
  .meta-mini{font-family:var(--mono); font-size:12px; color:var(--ink-3); text-align:right}

  /* ---- instrument chips (the global toggle) ---- */
  .chips{display:flex; flex-wrap:wrap; gap:8px; margin:18px 0 4px}
  .chip{display:inline-flex; align-items:center; gap:8px; cursor:pointer; user-select:none;
    border:1px solid var(--edge); background:var(--panel-2); padding:6px 12px 6px 10px;
    border-radius:999px; font-family:var(--mono); font-size:12px; color:var(--ink-2);
    transition:border-color .15s, color .15s, background .15s;}
  .chip:hover{border-color:rgba(255,255,255,.22)}
  .chip .dot{width:10px; height:10px; border-radius:50%; box-shadow:0 0 0 3px rgba(0,0,0,.35) inset;}
  .chip.off{color:var(--ink-3); opacity:.55}
  .chip.off .dot{filter:grayscale(1) brightness(.6)}
  .chip .val{color:var(--ink); font-weight:500}
  .chip-hint{font-family:var(--mono); font-size:11px; color:var(--ink-3); align-self:center; margin-left:4px}

  /* ---- tabs ---- */
  nav.tabs{display:flex; flex-wrap:wrap; gap:2px; margin:20px 0 18px;
    border-bottom:1px solid var(--edge); position:sticky; top:0; z-index:5;
    background:linear-gradient(var(--bg),var(--bg) 70%, rgba(10,14,19,.6)); padding-top:6px;}
  .tab{appearance:none; border:0; background:none; cursor:pointer; color:var(--ink-3);
    font-family:var(--mono); font-size:12px; letter-spacing:.04em; padding:9px 14px;
    border-bottom:2px solid transparent; transition:color .15s, border-color .15s;}
  .tab .num{color:var(--ink-3); margin-right:8px}
  .tab:hover{color:var(--ink-2)}
  .tab.active{color:var(--ink); border-bottom-color:var(--accent)}
  .tab.active .num{color:var(--accent)}

  /* ---- section + cards ---- */
  .section{display:none}
  .section.active{display:block; animation:fade .25s ease}
  @keyframes fade{from{opacity:0; transform:translateY(4px)} to{opacity:1; transform:none}}
  .section-intro{color:var(--ink-2); font-size:13px; margin:2px 0 18px; max-width:80ch}
  .grid{display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px}
  .card{grid-column:span 1; background:linear-gradient(180deg,var(--panel),var(--panel-2));
    border:1px solid var(--edge); border-radius:12px; padding:14px 14px 8px; min-width:0;}
  .card.wide{grid-column:span 2}
  .card-h{display:flex; flex-direction:column; gap:2px; margin-bottom:6px}
  .card-t{font-family:var(--disp); font-weight:600; font-size:14px; letter-spacing:.01em}
  .card-s{font-family:var(--mono); font-size:11px; color:var(--ink-3); line-height:1.45}
  .plot{width:100%; height:300px}
  .plot.tall{height:360px}
  .empty{display:flex; align-items:center; justify-content:center; height:260px;
    color:var(--ink-3); font-family:var(--mono); font-size:12px; text-align:center}
  .mgrid{display:flex; flex-wrap:wrap; gap:14px}
  .mcell{flex:1 1 220px; min-width:200px}
  .mcell .mt{font-family:var(--mono); font-size:11px; color:var(--ink-2); text-align:center; margin-bottom:2px}
  .mplot{height:240px}

  /* ---- tables ---- */
  table{width:100%; border-collapse:collapse; font-size:13px}
  th,td{text-align:left; padding:9px 10px; border-bottom:1px solid var(--edge-2)}
  th{font-family:var(--mono); font-size:11px; letter-spacing:.06em; text-transform:uppercase;
    color:var(--ink-3); font-weight:500}
  td{font-family:var(--mono); font-size:12px; color:var(--ink-2)}
  td.name{color:var(--ink)}
  .swatch{display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:8px; vertical-align:middle}
  .tag{font-family:var(--mono); font-size:11px; padding:2px 8px; border-radius:999px;
    border:1px solid var(--edge); color:var(--ink-2)}
  .tag.good{color:var(--good); border-color:rgba(94,240,168,.35)}
  .tag.bad{color:var(--bad); border-color:rgba(240,94,138,.35)}
  td.micro{font-size:11px; color:var(--ink-3); white-space:nowrap}
  .cap{margin-top:10px; font-family:var(--mono); font-size:11px; color:var(--ink-3); line-height:1.5}
  .cap code{background:var(--panel-2); padding:1px 5px; border-radius:4px; color:var(--ink-2)}

  footer{margin-top:36px; padding-top:16px; border-top:1px solid var(--edge);
    color:var(--ink-3); font-family:var(--mono); font-size:11px}
  @media (max-width:760px){ .grid{grid-template-columns:1fr} .card.wide{grid-column:span 1}
    h1{font-size:21px} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <span class="eyebrow">Statistical character</span>
      <h1 id="title"></h1>
      <span class="sub" id="subtitle"></span>
    </div>
    <div class="meta-mini" id="metamini"></div>
  </header>

  <div class="chips" id="chips"></div>

  <nav class="tabs" id="tabs"></nav>
  <main id="sections"></main>

  <footer>
    Built from market_stats.to_dict(). Direction is near-random in liquid FX; size, timing and
    range structure carry the forecastable signal. Validate any single-sample edge out-of-sample.
  </footer>
</div>

<script>
"use strict";
const PAYLOAD = /*__PAYLOAD__*/;
const A   = PAYLOAD.assets;
const COL = PAYLOAD.colors;
const R   = PAYLOAD.reports;
const state = { visible: new Set(A), section: null };

/* ---------------- small helpers ---------------- */
const MONO = "IBM Plex Mono, monospace";
function rep(a){ return R[a]; }
function visible(){ return A.filter(a => state.visible.has(a)); }
function color(a){ return COL[a]; }
function isNum(x){ return typeof x === "number" && isFinite(x); }
function read(obj, path){
  if(obj == null) return undefined;
  return path.split(".").reduce((o,k) => (o==null ? undefined : o[k]), obj);
}
function getItem(r, item){ return item.get ? item.get(r) : read(r, item.path); }
function safe(v){ return isNum(v) ? v : null; }
function num(x,d){ return isNum(x) ? Number(x).toFixed(d==null?4:d) : "\u2014"; }
function pct(x,d){ return isNum(x) ? (x*100).toFixed(d==null?1:d)+"%" : "\u2014"; }
function sci(x){ if(!isNum(x)) return "\u2014"; return (Math.abs(x)<1e-3 && x!==0) ? x.toExponential(2) : x.toFixed(5); }
function money(x){ return isNum(x) ? "$"+Math.round(x).toLocaleString() : "\u2014"; }
function lev(x){ return isNum(x) ? x.toFixed(2)+"\u00d7" : "\u2014"; }
function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1); }
function hexA(hex,a){
  const h=hex.replace("#",""); const r=parseInt(h.slice(0,2),16),
    g=parseInt(h.slice(2,4),16), b=parseInt(h.slice(4,6),16);
  return "rgba("+r+","+g+","+b+","+a+")";
}

/* ---------------- plotly base ---------------- */
const FONT = { family:"Inter, system-ui, sans-serif", color:"#aeb8c4", size:12 };
const CONFIG = { displayModeBar:false, responsive:true };
function axis(extra){
  return Object.assign({ gridcolor:"rgba(255,255,255,.06)", zerolinecolor:"rgba(255,255,255,.16)",
    linecolor:"rgba(255,255,255,.12)", tickfont:{family:MONO,size:11}, automargin:true }, extra||{});
}
function baseLayout(extra){
  const L = { paper_bgcolor:"rgba(0,0,0,0)", plot_bgcolor:"rgba(0,0,0,0)", font:FONT,
    margin:{l:58,r:18,t:16,b:42}, xaxis:axis(), yaxis:axis(),
    legend:{orientation:"h", y:1.16, x:0, font:{size:11}, bgcolor:"rgba(0,0,0,0)"},
    barmode:"group", bargap:0.28, bargroupgap:0.06,
    hoverlabel:{bgcolor:"#0d131b", bordercolor:"rgba(255,255,255,.15)", font:{family:MONO,size:12}},
    shapes:[], annotations:[], showlegend:true };
  return Object.assign(L, extra||{});
}
function applyRefs(layout, refs){
  if(!refs) return;
  refs.forEach(rf => {
    layout.shapes.push({ type:"line", xref:"paper", x0:0, x1:1, yref:"y", y0:rf.y, y1:rf.y,
      line:{ color:rf.color||"rgba(255,255,255,.30)", width:1, dash:"dot" } });
    if(rf.text) layout.annotations.push({ xref:"paper", x:1, yref:"y", y:rf.y, text:rf.text,
      showarrow:false, font:{size:10, color:rf.color||"rgba(255,255,255,.45)"},
      xanchor:"right", yanchor:"bottom" });
  });
}

/* ---------------- generic builders ---------------- */
// grouped bars: one bar-cluster per item label, one colour per asset
function metricBar(items, opts){
  opts = opts || {};
  const labels = items.map(i => i.label);
  let any = false;
  const traces = visible().map(a => {
    const r = rep(a);
    const ys = items.map(i => { const v = getItem(r, i); if(isNum(v)) any = true; return safe(v); });
    return { type:"bar", name:a, legendgroup:a, x:labels, y:ys,
      marker:{ color:color(a), line:{width:0} },
      hovertemplate:"<b>"+a+"</b><br>%{x}: %{y:"+(opts.fmt||".4f")+"}<extra></extra>" };
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  if(opts.percent) layout.yaxis.tickformat = opts.tickfmt || ".1%";
  if(opts.ytitle) layout.yaxis.title = { text:opts.ytitle, font:{size:11} };
  applyRefs(layout, opts.ref);
  return { traces, layout };
}
// one line per asset across xs; valueFn(report, x) -> number
function lineChart(xs, valueFn, opts){
  opts = opts || {};
  let any = false;
  const traces = visible().map(a => {
    const r = rep(a);
    const ys = xs.map(x => { const v = valueFn(r, x); if(isNum(v)) any = true; return safe(v); });
    return { type:"scatter", mode:"lines+markers", name:a, legendgroup:a, x:xs, y:ys,
      line:{color:color(a), width:2}, marker:{color:color(a), size:5}, connectgaps:false,
      hovertemplate:"<b>"+a+"</b><br>"+(opts.xlabel||"x")+"=%{x}<br>%{y:"+(opts.fmt||".5f")+"}<extra></extra>" };
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  if(opts.xtitle) layout.xaxis.title = { text:opts.xtitle, font:{size:11} };
  if(opts.ytitle) layout.yaxis.title = { text:opts.ytitle, font:{size:11} };
  if(opts.percent) layout.yaxis.tickformat = ".1%";
  if(opts.xvals){ layout.xaxis.tickvals = opts.xvals; }
  applyRefs(layout, opts.ref);
  return { traces, layout };
}

/* ---------------- chart definitions ---------------- */
const HOURS = Array.from({length:24}, (_,i)=>i);
const SESS  = ["sydney","tokyo","london","newyork"];
const DOW   = ["Mon","Tue","Wed","Thu","Fri"];
const MON   = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

const CHARTS = {
  /* overview */
  ov_table: { wide:true, title:"Instrument summary",
    sub:"Headline character per asset. Toggle assets with the chips above.",
    build(){ return { html: overviewTable() }; } },
  ov_head: { title:"Volatility at a glance",
    sub:"Annualised close-to-close vol and daily \u03c3 \u2014 same units, directly comparable.",
    build(){ return metricBar(
      [ {label:"Annualised vol", path:"volatility.annualised.close_to_close"},
        {label:"Daily \u03c3",   path:"probability.expected_move_bands.sigma_per_day"} ],
      { percent:true }); } },

  /* distribution */
  dist_fan: { wide:true, title:"Return quantile fan",
    sub:"mean (diamond), \u00b11\u03c3 (dashes), box = 25\u201375%, whiskers = 5\u201395%, ticks = 1/99% \u2014 all in log-return units, packed together for comparison.",
    build(){ return distFan(); } },
  dist_moments: { title:"Shape \u2014 skew & excess kurtosis",
    sub:"Both dimensionless moments. Excess kurtosis \u226b 0 means fat tails.",
    build(){ return metricBar(
      [ {label:"Skewness", path:"distribution.skewness"},
        {label:"Excess kurtosis", path:"distribution.excess_kurtosis"} ],
      { ref:[{y:0}] }); } },
  dist_tails: { title:"Tail heaviness",
    sub:"Hill tail index & Student-t dof \u2014 lower = fatter tails. Grouped because they measure the same thing.",
    build(){ return metricBar(
      [ {label:"Hill tail index", path:"distribution.hill_tail_index"},
        {label:"Student-t dof", path:"distribution.student_t_dof"} ],
      { fmt:".2f" }); } },
  dist_norm: { title:"Normality (Jarque\u2013Bera p)",
    sub:"p above 0.05 \u21d2 cannot reject normality. FX returns almost always sit far below.",
    build(){ return metricBar(
      [ {label:"Jarque\u2013Bera p", path:"distribution.jarque_bera_p"} ],
      { fmt:".3f", ref:[{y:0.05, text:"0.05"}] }); } },

  /* desk */
  desk_size: { wide:true, title:"Annualise & size the position",
    sub:"Steps 1\u20132: annualised vol/drift/Sharpe, the drift t-stat and bias, then the vol-target weight, notional and P&L \u03c3.",
    build(){ return deskSize(); } },
  desk_var: { title:"Daily loss limit (VaR ladder)",
    sub:"Step 4: empirical value-at-risk as a share of the book across confidence levels. Higher confidence = deeper tail = bigger limit.",
    build(){ return deskLadder("loss_limits","var_pct_book",{ bar:true, ytitle:"VaR (% of book)" }); } },
  desk_es: { title:"Expected shortfall ladder",
    sub:"Step 5: average loss on days worse than VaR (CVaR). Always \u2265 VaR; the gap widens with fatter tails.",
    build(){ return deskLadder("expected_shortfall","es_pct_book",{ ytitle:"ES (% of book)" }); } },
  desk_lev: { title:"Leverage \u2014 Kelly vs tail cap",
    sub:"Step 6: full-Kelly is growth-optimal for a thin-tailed bet; a fractional-Kelly haircut and the tail-index ceiling pull the usable maximum far below it.",
    build(){ return metricBar(
      [ {label:"Full Kelly", path:"desk.leverage.full_kelly"},
        {label:"Frac-Kelly", path:"desk.leverage.capped_kelly"},
        {label:"Tail cap", path:"desk.leverage.tail_cap"},
        {label:"Suggested max", path:"desk.leverage.suggested_max"} ],
      { fmt:".2f", ytitle:"leverage (\u00d7)" }); } },
  desk_hedge: { title:"Crash insurance (protective put)",
    sub:"Step 7: rough cost of a one-month put by strike, as a share of notional. Negative skew makes the out-of-the-money puts richer.",
    build(){ return deskHedge(); } },

  /* volatility */
  vol_estimators: { wide:true, title:"Annualised volatility estimators",
    sub:"Five OHLC estimators, identical units \u2014 the canonical 'pack similar values together' view. Spreads between them hint at gap / overnight behaviour.",
    build(){ return metricBar(
      [ {label:"Close\u2013Close", path:"volatility.annualised.close_to_close"},
        {label:"Parkinson", path:"volatility.annualised.parkinson"},
        {label:"Garman\u2013Klass", path:"volatility.annualised.garman_klass"},
        {label:"Rogers\u2013Satchell", path:"volatility.annualised.rogers_satchell"},
        {label:"Yang\u2013Zhang", path:"volatility.annualised.yang_zhang"} ],
      { percent:true }); } },
  vol_cones: { title:"Volatility cones",
    sub:"Band = 10\u201390% of historical rolling vol per window; line = median; \u2605 = current. Where the star sits in the band tells you if vol is rich or cheap now.",
    build(){ return volCones(); } },
  vol_garch: { title:"GARCH(1,1) parameters",
    sub:"alpha (shock), beta (memory), persistence = alpha+beta. All on 0\u20131, so they share an axis. Persistence near 1 \u21d2 vol shocks decay slowly.",
    build(){ return metricBar(
      [ {label:"alpha", path:"volatility.garch.alpha"},
        {label:"beta", path:"volatility.garch.beta"},
        {label:"persistence", path:"volatility.garch.persistence"},
        {label:"GJR gamma", path:"volatility.gjr_garch.gamma"} ],
      { fmt:".3f", ref:[{y:1, text:"1.0"}] }); } },
  vol_cluster: { title:"Volatility clustering",
    sub:"Ljung\u2013Box p on squared returns. p < 0.05 \u21d2 clustering present (ARCH effect) \u2014 the forecastable part.",
    build(){ return metricBar(
      [ {label:"Ljung\u2013Box p (sq returns)", path:"volatility.clustering_test.ljung_box_sq_returns_p"} ],
      { fmt:".3f", ref:[{y:0.05, text:"0.05"}] }); } },

  /* memory */
  mr_acf: { wide:true, title:"Return autocorrelation (ACF)",
    sub:"Lags 1\u201310 on one scale. Shaded region = approx 95% noise band (\u00b11.96/\u221an); points inside it are indistinguishable from zero.",
    build(){ return mrAcf(); } },
  mr_ljungbox: { title:"Ljung\u2013Box on returns (joint test)",
    sub:"p < 0.05 \u21d2 statistically not white noise. With large n even tiny, untradeable autocorrelations turn significant \u2014 read against the ACF magnitudes, not alone.",
    build(){ return mrLjungBox(); } },
  mr_vr: { title:"Variance ratio",
    sub:"q = 2/4/8/16. VR > 1 trending, < 1 mean-reverting, \u2248 1 random walk. Reference at 1.",
    build(){ return lineChart([2,4,8,16],
      (r,q)=>read(r,"mean_reversion.variance_ratio.q"+q+".vr"),
      { xtitle:"holding period q", xvals:[2,4,8,16], fmt:".3f", ref:[{y:1, text:"1.0"}] }); } },
  mr_hurst: { title:"Long-memory exponents",
    sub:"Hurst (R/S) and DFA both centre on 0.5 for a random walk \u2014 grouped on a shared axis with the 0.5 reference.",
    build(){ return metricBar(
      [ {label:"Hurst (R/S)", path:"mean_reversion.hurst_rs"},
        {label:"DFA", path:"mean_reversion.dfa_exponent"} ],
      { fmt:".3f", ref:[{y:0.5, text:"0.5"}] }); } },
  mr_halflife: { title:"Mean-reversion half-life",
    sub:"OU half-life in bars (blank = not mean-reverting on the level).",
    build(){ return metricBar(
      [ {label:"Half-life (bars)", path:"mean_reversion.half_life_bars"} ],
      { fmt:".1f", ytitle:"bars" }); } },

  /* sessions */
  sess_profile: { wide:true, title:"Intraday volatility profile",
    sub:"Mean |log return| by hour (your tz). Overlaid so you can line up each asset's active window.",
    build(){ return lineChart(HOURS,
      (r,h)=>read(r,"sessions.intraday_vol_profile_abs_ret."+h),
      { xtitle:"hour", xlabel:"hour", fmt:".5f", noteKey:"sessions" }); } },
  sess_range: { title:"Session range share",
    sub:"Each session's average range as a fraction of that asset's full-day range \u2014 normalised so assets of different price scale compare directly.",
    build(){ return sessRange(); } },
  sess_form: { title:"Daily high / low formation hour",
    sub:"When the day's extreme tends to print. Solid = high, dashed = low.",
    build(){ return sessForm(); } },
  sess_overlap: { title:"London/NY overlap & gaps",
    sub:"Overlap share of the daily range, plus mean and 95th-pct absolute gap (fractional, comparable).",
    build(){ return metricBar(
      [ {label:"Overlap share", path:"sessions.overlap_range_share_of_day"},
        {label:"Mean |gap|", path:"sessions.gap_stats.mean_abs_gap"},
        {label:"95% |gap|", path:"sessions.gap_stats.p95_abs_gap"} ],
      { percent:true, tickfmt:".2%" }); } },

  /* calendar */
  cal_dow: { title:"Day-of-week activity",
    sub:"Mean |log return| by weekday (return space \u2014 comparable across assets).",
    build(){ return metricBar(
      DOW.map(d=>({label:d, path:"calendar.day_of_week."+d+".mean_abs_ret"})),
      { fmt:".5f" }); } },
  cal_month: { title:"Month-of-year volatility",
    sub:"Annualised vol by calendar month \u2014 the robust part of seasonality.",
    build(){ return lineChart(MON.map((_,i)=>i),
      (r,i)=>read(r,"calendar.month_of_year."+MON[i]+".ann_vol"),
      { xtitle:"month", percent:true, xvals:MON.map((_,i)=>i),
        ticktext:MON, fmt:".2%" }); } },
  cal_tom: { title:"Turn-of-month effect",
    sub:"Mean |move| in the first/last two trading days vs the rest of the month.",
    build(){ return metricBar(
      [ {label:"Turn of month", path:"calendar.turn_of_month.turn_of_month_mean_abs"},
        {label:"Rest of month", path:"calendar.turn_of_month.rest_of_month_mean_abs"} ],
      { fmt:".5f" }); } },

  /* probability */
  prob_dir: { title:"Directional probabilities",
    sub:"All cluster near 50% in liquid FX \u2014 grouped with the 0.5 reference so any edge is obvious.",
    build(){ return metricBar(
      [ {label:"P(up)",            get:r=>(read(r,"probability.conditional_direction")||{})["P(up)"]},
        {label:"P(up | up today)", get:r=>(read(r,"probability.conditional_direction")||{})["P(up_next | up_today)"]},
        {label:"P(up | dn today)", get:r=>(read(r,"probability.conditional_direction")||{})["P(up_next | down_today)"]} ],
      { percent:true, ref:[{y:0.5, text:"0.5"}] }); } },
  prob_markov: { wide:true, title:"Markov transition matrices",
    sub:"P(next state | current state) over down / flat / up return terciles, one matrix per asset.",
    build(){ return markovGrid(); } },
  prob_touch: { title:"Touch probability over ~1 day",
    sub:"Empirical chance price touches \u00b1k\u03c3 (bars), with the analytic reflection benchmark (diamonds).",
    build(){ return probTouch(); } },
  prob_emove: { title:"Expected move (\u03c3)",
    sub:"Per-bar and per-day \u03c3 in return space \u2014 comparable across assets.",
    build(){ return metricBar(
      [ {label:"\u03c3 / bar", path:"probability.expected_move_bands.sigma_per_bar"},
        {label:"\u03c3 / day", path:"probability.expected_move_bands.sigma_per_day"} ],
      { percent:true, tickfmt:".2%" }); } },
  prob_horizon: { title:"Horizon outcome (bootstrap)",
    sub:"Stationary-block bootstrap over the horizon: terminal-return spread and median worst drawdown.",
    build(){ return metricBar(
      [ {label:"Term 5%",  path:"probability.bootstrap.terminal_return_p05"},
        {label:"Term 50%", path:"probability.bootstrap.terminal_return_median"},
        {label:"Term 95%", path:"probability.bootstrap.terminal_return_p95"},
        {label:"Max DD 50%", path:"probability.bootstrap.max_drawdown_median"},
        {label:"Max DD 5%",  path:"probability.bootstrap.max_drawdown_p05"} ],
      { percent:true, tickfmt:".2%", ref:[{y:0}] }); } },
  prob_mfe: { title:"Forward excursion (MFE / MAE)",
    sub:"Best/worst forward move over the horizon, as a fraction of price (long perspective).",
    build(){ return metricBar(
      [ {label:"MFE 50%", path:"probability.mfe_mae.mfe_median"},
        {label:"MFE 90%", path:"probability.mfe_mae.mfe_p90"},
        {label:"MAE 50%", path:"probability.mfe_mae.mae_median"},
        {label:"MAE 10%", path:"probability.mfe_mae.mae_p10"} ],
      { percent:true, tickfmt:".2%", ref:[{y:0}] }); } },

  /* regimes */
  reg_share: { title:"Regime time-share",
    sub:"Share of bars spent in each volatility regime (Gaussian-mixture clustering).",
    build(){ return regimeBar("share_of_time", true); } },
  reg_vol: { title:"Regime annualised vol",
    sub:"Realised annualised vol inside each regime \u2014 the gap is what 'regime' means here.",
    build(){ return regimeBar("ann_vol", true); } },
  reg_info: { wide:true, title:"Current regime & switches",
    sub:"Where each asset sits now and how often it has switched in-sample.",
    build(){ return { html: regimeTable() }; } },
};

/* ---- bespoke builders ---- */
function distFan(){
  const traces = []; let any = false;
  visible().forEach(a => {
    const d = read(rep(a), "distribution"); if(!d || d.note) return;
    const q = d.empirical_quantiles || {}; if(q["0.5"] == null) return;
    any = true; const c = color(a);
    traces.push({ type:"box", orientation:"h", name:a, legendgroup:a, y:[a],
      lowerfence:[safe(q["0.05"])], q1:[safe(q["0.25"])], median:[safe(q["0.5"])],
      q3:[safe(q["0.75"])], upperfence:[safe(q["0.95"])],
      mean:[safe(d.mean)], sd:[safe(d.std)], boxmean:"sd",
      marker:{color:c}, line:{color:c, width:1.5}, fillcolor:hexA(c,0.16),
      whiskerwidth:0.5, width:0.55,
      hovertemplate:"<b>"+a+"</b><br>5% "+sci(q["0.05"])+" / 25% "+sci(q["0.25"])+
        "<br>50% "+sci(q["0.5"])+"<br>75% "+sci(q["0.75"])+" / 95% "+sci(q["0.95"])+
        "<br>mean "+sci(d.mean)+"  sd "+sci(d.std)+"<extra></extra>" });
    traces.push({ type:"scatter", mode:"markers", legendgroup:a, showlegend:false,
      x:[safe(q["0.01"]), safe(q["0.99"])], y:[a,a],
      marker:{symbol:"line-ns-open", size:16, color:c, line:{width:1.5}},
      hovertemplate:"%{x:.6f}<extra></extra>" });
  });
  if(!any) return { empty:true };
  const layout = baseLayout({ showlegend:false });
  layout.xaxis.title = { text:"log return", font:{size:11} };
  layout.xaxis.zeroline = true;
  return { traces, layout };
}

function volCones(){
  const wins = ["10bar","20bar","60bar","120bar"], xs = [10,20,60,120];
  const traces = []; let any = false;
  visible().forEach(a => {
    const c = read(rep(a), "volatility.volatility_cones"); if(!c) return;
    const med = wins.map(w => safe(read(c, w+".median")));
    const p10 = wins.map(w => safe(read(c, w+".p10")));
    const p90 = wins.map(w => safe(read(c, w+".p90")));
    const cur = wins.map(w => safe(read(c, w+".current")));
    if(med.every(v => v == null)) return; any = true; const cc = color(a);
    traces.push({ type:"scatter", x:xs, y:p90, mode:"lines", line:{width:0},
      legendgroup:a, showlegend:false, hoverinfo:"skip" });
    traces.push({ type:"scatter", x:xs, y:p10, mode:"lines", line:{width:0}, fill:"tonexty",
      fillcolor:hexA(cc,0.10), legendgroup:a, showlegend:false, hoverinfo:"skip" });
    traces.push({ type:"scatter", x:xs, y:med, mode:"lines+markers", name:a, legendgroup:a,
      line:{color:cc, width:2}, marker:{color:cc, size:6},
      hovertemplate:"<b>"+a+"</b> %{x}-bar<br>median %{y:.2%}<extra></extra>" });
    traces.push({ type:"scatter", x:xs, y:cur, mode:"markers", legendgroup:a, showlegend:false,
      marker:{symbol:"star", color:cc, size:12, line:{width:1, color:"#0a0e13"}},
      hovertemplate:"<b>"+a+"</b> %{x}-bar<br>current %{y:.2%}<extra></extra>" });
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  layout.xaxis.type = "log"; layout.xaxis.tickvals = xs; layout.xaxis.ticktext = xs.map(String);
  layout.xaxis.title = { text:"window (bars)", font:{size:11} };
  layout.yaxis.tickformat = ".1%"; layout.yaxis.title = { text:"annualised vol", font:{size:11} };
  return { traces, layout };
}

function mrAcf(){
  const lags = [1,2,3,4,5,6,7,8,9,10];
  const res = lineChart(lags, (r,k)=>read(r,"mean_reversion.acf_returns.lag"+k),
    { xtitle:"lag", xlabel:"lag", fmt:".4f", xvals:lags, ref:[{y:0}] });
  if(res.empty) return res;
  const ns = visible().map(a => read(rep(a),"distribution.n_returns")).filter(isNum);
  if(ns.length){
    const band = 1.96 / Math.sqrt(Math.min.apply(null, ns));
    res.layout.shapes.push({ type:"rect", xref:"paper", x0:0, x1:1, yref:"y",
      y0:-band, y1:band, fillcolor:"rgba(255,255,255,.05)", line:{width:0}, layer:"below" });
    applyRefs(res.layout, [{y:band, text:"95% band", color:"rgba(255,255,255,.28)"},
                           {y:-band, color:"rgba(255,255,255,.28)"}]);
  }
  return res;
}

function mrLjungBox(){
  const xs = [], ys = [], cols = [], txt = [];
  visible().forEach(a => {
    const mr = read(rep(a), "mean_reversion"); if(!mr || mr.note) return;
    const p = read(mr, "ljung_box_returns_p");
    if(!isNum(p)) return;
    xs.push(a); ys.push(p); cols.push(color(a));
    const stat = read(mr, "ljung_box_returns_stat");
    const verd = mr.verdict || "";
    txt.push("stat "+num(stat,1)+(verd?("<br>"+verd):""));
  });
  if(!xs.length) return { empty:true };
  const traces = [{ type:"bar", x:xs, y:ys, marker:{color:cols}, width:0.5,
    customdata:txt, hovertemplate:"<b>%{x}</b><br>p = %{y:.4f}<br>%{customdata}<extra></extra>" }];
  const layout = baseLayout({ showlegend:false, bargap:0.4 });
  layout.yaxis.title = { text:"Ljung\u2013Box p", font:{size:11} };
  applyRefs(layout, [{y:0.05, text:"0.05", color:"rgba(240,179,94,.6)"}]);
  return { traces, layout };
}

function sessRange(){
  let any = false;
  const traces = visible().map(a => {
    const r = rep(a);
    const full = read(r, "sessions.full_day_avg_range");
    const ys = SESS.map(s => {
      const v = read(r, "sessions.session_avg_range."+s);
      const out = (isNum(v) && isNum(full) && full>0) ? v/full : null;
      if(isNum(out)) any = true; return out;
    });
    return { type:"bar", name:a, legendgroup:a, x:SESS.map(cap), y:ys, marker:{color:color(a)},
      hovertemplate:"<b>"+a+"</b><br>%{x}: %{y:.0%} of full-day range<extra></extra>" };
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  layout.yaxis.tickformat = ".0%";
  return { traces, layout };
}

function sessForm(){
  const traces = []; let any = false;
  visible().forEach(a => {
    const hi = read(rep(a), "sessions.daily_high_formation_hour_dist");
    const lo = read(rep(a), "sessions.daily_low_formation_hour_dist");
    if(!hi && !lo) return;
    const c = color(a);
    if(hi){ any = true; traces.push({ type:"scatter", mode:"lines", name:a+" high", legendgroup:a,
      x:HOURS, y:HOURS.map(h=>safe(hi[h])), line:{color:c, width:2},
      hovertemplate:"<b>"+a+" high</b><br>%{x}:00 \u2192 %{y:.0%}<extra></extra>" }); }
    if(lo){ any = true; traces.push({ type:"scatter", mode:"lines", name:a+" low", legendgroup:a,
      showlegend:false, x:HOURS, y:HOURS.map(h=>safe(lo[h])), line:{color:c, width:1.5, dash:"dot"},
      hovertemplate:"<b>"+a+" low</b><br>%{x}:00 \u2192 %{y:.0%}<extra></extra>" }); }
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  layout.xaxis.title = { text:"hour", font:{size:11} };
  layout.yaxis.tickformat = ".0%";
  return { traces, layout };
}

function markovGrid(){
  const states = ["down","flat","up"];
  const grid = visible().map(a => {
    const m = read(rep(a), "probability.markov_transition");
    if(!m || m.note) return null;
    const z = states.map(f => states.map(t => safe(m[f] && m[f][t])));
    const txt = z.map(row => row.map(v => v==null ? "" : (v*100).toFixed(0)+"%"));
    return { title:a, traces:[{ type:"heatmap", z:z, x:states, y:states,
      colorscale:[[0,"#0d131b"],[0.5,hexA(color(a),0.45)],[1,color(a)]], zmin:0, zmax:1,
      showscale:false, text:txt, texttemplate:"%{text}",
      textfont:{family:MONO, size:13, color:"#0a0e13"}, xgap:3, ygap:3,
      hovertemplate:"from %{y} \u2192 %{x}: %{z:.1%}<extra></extra>" }],
      layout: baseLayout({ showlegend:false, margin:{l:50,r:8,t:26,b:30},
        xaxis:{ side:"top", tickfont:{family:MONO,size:11}, title:{text:"to",font:{size:10}} },
        yaxis:{ autorange:"reversed", tickfont:{family:MONO,size:11}, title:{text:"from",font:{size:10}} } }) };
  }).filter(Boolean);
  return grid.length ? { grid } : { empty:true };
}

function probTouch(){
  const ks = ["1sigma","2sigma","3sigma"], labels = ["\u00b11\u03c3","\u00b12\u03c3","\u00b13\u03c3"];
  let any = false;
  const traces = visible().map(a => {
    const e = read(rep(a), "probability.touch_probability.empirical");
    const ys = ks.map(k => { const v = (e && !e.note) ? e[k] : null; if(isNum(v)) any=true; return safe(v); });
    return { type:"bar", name:a, legendgroup:a, x:labels, y:ys, marker:{color:color(a)},
      hovertemplate:"<b>"+a+"</b> %{x}<br>empirical %{y:.0%}<extra></extra>" };
  });
  const first = visible()[0];
  const an = first ? read(rep(first), "probability.touch_probability.analytic_reflection") : null;
  if(an){ traces.push({ type:"scatter", mode:"markers", name:"analytic", x:labels,
    y:ks.map(k=>safe(an[k])), marker:{symbol:"diamond-open", size:13, color:"#e6edf3", line:{width:1.5}},
    hovertemplate:"analytic %{y:.0%}<extra></extra>" }); any = true; }
  if(!any) return { empty:true };
  const layout = baseLayout({}); layout.yaxis.tickformat = ".0%";
  return { traces, layout };
}

function regimeBar(field, percent){
  const labels = ["low_vol","high_vol"];
  let any = false;
  const traces = visible().map(a => {
    const ps = read(rep(a), "regimes.per_state");
    const ys = labels.map(l => { const v = ps && ps[l] ? ps[l][field] : null; if(isNum(v)) any=true; return safe(v); });
    return { type:"bar", name:a, legendgroup:a, x:["low vol","high vol"], y:ys, marker:{color:color(a)},
      hovertemplate:"<b>"+a+"</b> %{x}<br>%{y:"+(percent?".1%":".4f")+"}<extra></extra>" };
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  if(percent) layout.yaxis.tickformat = ".0%";
  return { traces, layout };
}

/* ---- HTML tables ---- */
function overviewTable(){
  let h = "<table><thead><tr><th>Instrument</th><th>Bars</th><th>Span</th>"
        + "<th>~bars/day</th><th>Character</th><th>Regime now</th><th>Ann vol</th><th>Normal?</th></tr></thead><tbody>";
  visible().forEach(a => {
    const r = rep(a), m = r.meta || {};
    const span = (m.start && m.end) ? (String(m.start).slice(0,10)+" \u2192 "+String(m.end).slice(0,10)) : "\u2014";
    const bpd = isNum(m.bars_per_year) ? (m.bars_per_year/252).toFixed(1) : "\u2014";
    const verdict = read(r,"mean_reversion.verdict") || "\u2014";
    const reg = read(r,"regimes.current_regime") || "\u2014";
    const vol = pct(read(r,"volatility.annualised.close_to_close"),1);
    const normal = read(r,"distribution.is_normal_5pct");
    const ntag = normal===true ? "<span class='tag good'>yes</span>"
               : normal===false ? "<span class='tag bad'>no</span>" : "<span class='tag'>\u2014</span>";
    h += "<tr><td class='name'><span class='swatch' style='background:"+color(a)+"'></span>"+a+"</td>"
      + "<td>"+(m.n_bars!=null?m.n_bars:"\u2014")+"</td><td>"+span+"</td><td>"+bpd+"</td>"
      + "<td>"+verdict+"</td><td>"+reg.replace("_"," ")+"</td><td>"+vol+"</td><td>"+ntag+"</td></tr>";
  });
  return h + "</tbody></table>";
}

function regimeTable(){
  let h = "<table><thead><tr><th>Instrument</th><th>Current regime</th><th>Switch points</th>"
        + "<th>Last switch</th><th>Low-vol share</th><th>High-vol share</th></tr></thead><tbody>";
  visible().forEach(a => {
    const r = rep(a), reg = read(r,"regimes");
    if(!reg || reg.note){ h += "<tr><td class='name'><span class='swatch' style='background:"+color(a)
      +"'></span>"+a+"</td><td colspan='5'>"+(reg&&reg.note?reg.note:"\u2014")+"</td></tr>"; return; }
    const cur = (reg.current_regime||"\u2014").replace("_"," ");
    const last = reg.last_switch ? String(reg.last_switch).slice(0,16) : "\u2014";
    const lo = pct(read(reg,"per_state.low_vol.share_of_time"),0);
    const hi = pct(read(reg,"per_state.high_vol.share_of_time"),0);
    h += "<tr><td class='name'><span class='swatch' style='background:"+color(a)+"'></span>"+a+"</td>"
      + "<td>"+cur+"</td><td>"+(reg.n_switch_points!=null?reg.n_switch_points:"\u2014")+"</td>"
      + "<td>"+last+"</td><td>"+lo+"</td><td>"+hi+"</td></tr>";
  });
  return h + "</tbody></table>";
}

/* ---------------- desk builders ---------------- */
// annualisation + vol-target sizing, one row per instrument
function deskSize(){
  let any = false;
  let h = "<table><thead><tr><th>Instrument</th><th>Ann vol</th><th>Ann drift</th>"
        + "<th>Ann Sharpe</th><th>t(mean)</th><th>Bias</th><th>Weight</th>"
        + "<th>Notional</th><th>Daily P&amp;L \u03c3</th><th>Annual P&amp;L \u03c3</th></tr></thead><tbody>";
  visible().forEach(a => {
    const dk = read(rep(a), "desk"); if(!dk || dk.note) return;
    any = true;
    const an = dk.annualized || {}, sz = dk.sizing || {};
    h += "<tr><td class='name'><span class='swatch' style='background:"+color(a)+"'></span>"+a+"</td>"
      + "<td>"+pct(an.vol,1)+"</td><td>"+pct(an.drift,1)+"</td><td>"+num(an.sharpe,2)+"</td>"
      + "<td>"+num(an.t_stat,2)+"</td><td class='micro'>"+(an.bias||"\u2014")+"</td>"
      + "<td>"+num(sz.weight,2)+"</td><td>"+money(sz.notional)+"</td>"
      + "<td>"+money(sz.daily_pl_sd)+"</td><td>"+money(sz.annual_pl_sd)+"</td></tr>";
  });
  if(!any) return { empty:true };
  return { html: h + "</tbody></table><div class='cap'>Defaults: book "
    + money(read(rep(visible()[0]),"desk.params.book")) + ", target sleeve vol "
    + pct(read(rep(visible()[0]),"desk.params.target_vol"),0)
    + ". Recompute with other values via <code>desk_distribution()</code>.</div>" };
}
// VaR or ES ladder across confidence levels; arr = payload array name, key = value field
function deskLadder(arrName, key, opts){
  opts = opts || {};
  const traces = []; let any = false; let tickvals = null;
  visible().forEach(a => {
    const arr = read(rep(a), "desk."+arrName); if(!arr || !arr.length) return;
    const xs = arr.map(o => o.confidence*100);
    const ys = arr.map(o => safe(o[key]));
    if(ys.every(v => v == null)) return; any = true; tickvals = tickvals || xs;
    traces.push({ type: opts.bar?"bar":"scatter", mode: opts.bar?undefined:"lines+markers",
      name:a, legendgroup:a, x:xs, y:ys, marker:{color:color(a)}, line:{color:color(a), width:2},
      hovertemplate:"<b>"+a+"</b><br>%{x}% conf \u2192 %{y:.2%} of book<extra></extra>" });
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  layout.xaxis.title = { text:"confidence level (%)", font:{size:11} };
  if(tickvals) layout.xaxis.tickvals = tickvals;
  layout.yaxis.tickformat = ".1%";
  layout.yaxis.title = { text:opts.ytitle||"% of book", font:{size:11} };
  return { traces, layout };
}
// protective-put cost by strike, grouped by instrument
function deskHedge(){
  const traces = []; let any = false;
  visible().forEach(a => {
    const arr = read(rep(a), "desk.crash_insurance"); if(!arr || !arr.length) return;
    const lbl = arr.map(o => o.otm_pct>0 ? ("\u2212"+Math.round(o.otm_pct*100)+"% put") : "ATM put");
    const ys = arr.map(o => safe(o.cost_pct_notional));
    if(ys.every(v => v == null)) return; any = true;
    traces.push({ type:"bar", name:a, legendgroup:a, x:lbl, y:ys, marker:{color:color(a)},
      hovertemplate:"<b>"+a+"</b><br>%{x}: %{y:.2%} of notional<extra></extra>" });
  });
  if(!any) return { empty:true };
  const layout = baseLayout({});
  layout.yaxis.tickformat = ".2%";
  layout.yaxis.title = { text:"cost (% of notional)", font:{size:11} };
  return { traces, layout };
}

/* ---------------- sections ---------------- */
const SECTIONS = [
  { id:"overview", label:"Overview",
    intro:"Headline character per instrument. Everything below drills into one metric group; toggle assets with the chips and they update across every chart.",
    charts:["ov_table","ov_head"] },
  { id:"distribution", label:"Distribution",
    intro:"How returns are shaped: location, spread, asymmetry and tail weight. Similar magnitudes are packed onto shared axes.",
    charts:["dist_fan","dist_moments","dist_tails","dist_norm"] },
  { id:"desk", label:"Desk",
    intro:"The distribution turned into desk decisions: annualisation, vol-target sizing, a VaR / expected-shortfall ladder, a Kelly-capped leverage ceiling, and crash-insurance cost. Defaults assume a book of 1,000,000 and a 10% sleeve vol target \u2014 both configurable via desk_distribution() in market_stats.",
    charts:["desk_size","desk_var","desk_es","desk_lev","desk_hedge"] },
  { id:"volatility", label:"Volatility",
    intro:"Level, estimator agreement, the cone of where vol sits today, and whether it clusters \u2014 the most forecastable dimension.",
    charts:["vol_estimators","vol_cones","vol_garch","vol_cluster"] },
  { id:"memory", label:"Memory",
    intro:"Mean reversion vs trend vs random walk: autocorrelation, the joint Ljung\u2013Box test, variance ratios, long-memory exponents and reversion speed.",
    charts:["mr_acf","mr_ljungbox","mr_vr","mr_hurst","mr_halflife"] },
  { id:"sessions", label:"Sessions",
    intro:"Intraday structure: when each instrument is active, how range concentrates by session, and where daily extremes print. Needs intraday bars.",
    charts:["sess_profile","sess_range","sess_form","sess_overlap"] },
  { id:"calendar", label:"Calendar",
    intro:"Weekday and monthly seasonality. Treat directional effects with suspicion; volatility seasonality is the robust part.",
    charts:["cal_dow","cal_month","cal_tom"] },
  { id:"probability", label:"Probability",
    intro:"Forward-looking move probabilities: direction, state transitions, touch odds, expected range and bootstrapped horizon outcomes.",
    charts:["prob_dir","prob_markov","prob_touch","prob_emove","prob_horizon","prob_mfe"] },
  { id:"regimes", label:"Regimes",
    intro:"Volatility-regime clustering: how time splits between calm and turbulent states, how different they are, and where each sits now.",
    charts:["reg_share","reg_vol","reg_info"] },
];

/* ---------------- rendering ---------------- */
function buildHeader(){
  document.getElementById("title").textContent = PAYLOAD.title;
  document.getElementById("subtitle").textContent =
    "Log-return statistical character \u00b7 " + A.length + (A.length===1?" instrument":" instruments");
  const spans = A.map(a => read(rep(a),"meta.n_bars")).filter(isNum);
  const totalBars = spans.reduce((s,v)=>s+v,0);
  document.getElementById("metamini").innerHTML =
    A.length + " assets \u00b7 " + totalBars.toLocaleString() + " bars total<br>" +
    "click a chip to add/remove an instrument";
}

function buildChips(){
  const wrap = document.getElementById("chips");
  A.forEach(a => {
    const c = document.createElement("div");
    c.className = "chip"; c.dataset.asset = a;
    const vol = read(rep(a),"volatility.annualised.close_to_close");
    c.innerHTML = "<span class='dot' style='background:"+color(a)+"'></span>" + a +
      "<span class='val'>" + pct(vol,1) + "</span>";
    c.addEventListener("click", () => toggleAsset(a));
    wrap.appendChild(c);
  });
  const hint = document.createElement("span");
  hint.className = "chip-hint"; hint.textContent = "value = annualised vol";
  wrap.appendChild(hint);
  syncChips();
}
function syncChips(){
  document.querySelectorAll(".chip[data-asset]").forEach(c => {
    c.classList.toggle("off", !state.visible.has(c.dataset.asset));
  });
}
function toggleAsset(a){
  if(state.visible.has(a)){
    if(state.visible.size === 1) return;   // keep at least one
    state.visible.delete(a);
  } else state.visible.add(a);
  syncChips();
  renderSection(state.section);
}

function buildTabs(){
  const nav = document.getElementById("tabs");
  const main = document.getElementById("sections");
  SECTIONS.forEach((s,i) => {
    const b = document.createElement("button");
    b.className = "tab"; b.dataset.sec = s.id;
    b.innerHTML = "<span class='num'>"+String(i+1).padStart(2,"0")+"</span>"+s.label;
    b.addEventListener("click", () => activate(s.id));
    nav.appendChild(b);

    const sec = document.createElement("section");
    sec.className = "section"; sec.id = "sec-"+s.id;
    sec.innerHTML = "<p class='section-intro'>"+s.intro+"</p><div class='grid' id='grid-"+s.id+"'></div>";
    main.appendChild(sec);
  });
}

function activate(id){
  state.section = id;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.sec===id));
  document.querySelectorAll(".section").forEach(s => s.classList.toggle("active", s.id==="sec-"+id));
  renderSection(id);
}

function makeCard(def){
  const card = document.createElement("div");
  card.className = "card" + (def.wide ? " wide" : "");
  card.innerHTML = "<div class='card-h'><span class='card-t'>"+def.title+"</span>" +
    "<span class='card-s'>"+def.sub+"</span></div>";
  const body = document.createElement("div");
  card.appendChild(body);
  return { card, body };
}

function renderSection(id){
  const sec = SECTIONS.find(s => s.id === id); if(!sec) return;
  const grid = document.getElementById("grid-"+id);
  // purge any existing plots to free Plotly state
  grid.querySelectorAll(".js-plotly-plot").forEach(p => { try{ Plotly.purge(p); }catch(e){} });
  grid.innerHTML = "";

  sec.charts.forEach(cid => {
    const def = CHARTS[cid]; if(!def) return;
    const { card, body } = makeCard(def);
    grid.appendChild(card);
    let res;
    try { res = def.build(); }
    catch(e){ res = { empty:true, msg:"could not render ("+e.message+")" }; }

    if(res.empty){
      body.innerHTML = "<div class='empty'>"+(res.msg||"No data for the selected assets.")+"</div>";
    } else if(res.html != null){
      body.innerHTML = res.html;
    } else if(res.grid){
      const row = document.createElement("div"); row.className = "mgrid";
      res.grid.forEach(g => {
        const cell = document.createElement("div"); cell.className = "mcell";
        cell.innerHTML = "<div class='mt'>"+g.title+"</div>";
        const pdiv = document.createElement("div"); pdiv.className = "mplot";
        cell.appendChild(pdiv); row.appendChild(cell);
        Plotly.newPlot(pdiv, g.traces, g.layout, CONFIG);
      });
      body.appendChild(row);
    } else {
      const pdiv = document.createElement("div");
      pdiv.className = "plot" + (def.wide ? " tall" : "");
      body.appendChild(pdiv);
      Plotly.newPlot(pdiv, res.traces, res.layout, CONFIG);
    }
  });
}

/* ---------------- boot ---------------- */
buildHeader();
buildChips();
buildTabs();
activate(SECTIONS[0].id);
window.addEventListener("resize", () => {
  document.querySelectorAll(".section.active .js-plotly-plot").forEach(p => { try{ Plotly.Plots.resize(p); }catch(e){} });
});
</script>
</body>
</html>
'''